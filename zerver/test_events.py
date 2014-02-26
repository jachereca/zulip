# -*- coding: utf-8 -*-
from django.test import TestCase

from zerver.models import (
    get_client, get_realm, get_stream, get_user_profile_by_email,
    Recipient,
)

from zerver.lib.actions import (
    apply_events,
    create_stream_if_needed,
    do_add_alert_words,
    do_add_realm_filter,
    do_add_realm_emoji,
    do_change_full_name,
    do_change_is_admin,
    do_change_stream_description,
    do_remove_alert_words,
    do_remove_realm_emoji,
    do_remove_realm_filter,
    do_remove_subscription,
    do_rename_stream,
    do_set_muted_topics,
    do_set_realm_name,
    do_update_pointer,
    do_create_user,
    do_regenerate_api_key,
    fetch_initial_state_data,
)

from zerver.lib.event_queue import allocate_client_descriptor
from zerver.lib.test_helpers import AuthedTestCase, POSTRequestMock
from zerver.lib.validator import (
    check_bool, check_dict, check_int, check_list, check_string,
    equals, check_none_or
)

from zerver.views import _default_all_public_streams, _default_narrow

from zerver.tornadoviews import get_events_backend

from collections import OrderedDict
import ujson


class GetEventsTest(AuthedTestCase):
    def tornado_call(self, view_func, user_profile, post_data,
                     callback=None):
        request = POSTRequestMock(post_data, user_profile, callback)
        return view_func(request, user_profile)

    def test_get_events(self):
        email = "hamlet@zulip.com"
        recipient_email = "othello@zulip.com"
        user_profile = get_user_profile_by_email(email)
        recipient_user_profile = get_user_profile_by_email(recipient_email)
        self.login(email)

        result = self.tornado_call(get_events_backend, user_profile,
                                   {"apply_markdown": ujson.dumps(True),
                                    "event_types": ujson.dumps(["message"]),
                                    "user_client": "website",
                                    "dont_block": ujson.dumps(True),
                                    })
        self.assert_json_success(result)
        queue_id = ujson.loads(result.content)["queue_id"]

        recipient_result = self.tornado_call(get_events_backend, recipient_user_profile,
                                             {"apply_markdown": ujson.dumps(True),
                                              "event_types": ujson.dumps(["message"]),
                                              "user_client": "website",
                                              "dont_block": ujson.dumps(True),
                                              })
        self.assert_json_success(recipient_result)
        recipient_queue_id = ujson.loads(recipient_result.content)["queue_id"]

        result = self.tornado_call(get_events_backend, user_profile,
                                   {"queue_id": queue_id,
                                    "user_client": "website",
                                    "last_event_id": -1,
                                    "dont_block": ujson.dumps(True),
                                    })
        events = ujson.loads(result.content)["events"]
        self.assert_json_success(result)
        self.assert_length(events, 0, True)

        local_id = 10.01
        self.send_message(email, recipient_email, Recipient.PERSONAL, "hello", local_id=local_id, sender_queue_id=queue_id)

        result = self.tornado_call(get_events_backend, user_profile,
                                   {"queue_id": queue_id,
                                    "user_client": "website",
                                    "last_event_id": -1,
                                    "dont_block": ujson.dumps(True),
                                    })
        events = ujson.loads(result.content)["events"]
        self.assert_json_success(result)
        self.assert_length(events, 1, True)
        self.assertEqual(events[0]["type"], "message")
        self.assertEqual(events[0]["message"]["sender_email"], email)
        self.assertEqual(events[0]["local_message_id"], local_id)
        last_event_id = events[0]["id"]
        local_id += 0.01

        self.send_message(email, recipient_email, Recipient.PERSONAL, "hello", local_id=local_id, sender_queue_id=queue_id)

        result = self.tornado_call(get_events_backend, user_profile,
                                   {"queue_id": queue_id,
                                    "user_client": "website",
                                    "last_event_id": last_event_id,
                                    "dont_block": ujson.dumps(True),
                                    })
        events = ujson.loads(result.content)["events"]
        self.assert_json_success(result)
        self.assert_length(events, 1, True)
        self.assertEqual(events[0]["type"], "message")
        self.assertEqual(events[0]["message"]["sender_email"], email)
        self.assertEqual(events[0]["local_message_id"], local_id)

        # Test that the received message in the receiver's event queue
        # exists and does not contain a local id
        recipient_result = self.tornado_call(get_events_backend, recipient_user_profile,
                                             {"queue_id": recipient_queue_id,
                                              "user_client": "website",
                                              "last_event_id": -1,
                                              "dont_block": ujson.dumps(True),
                                              })
        recipient_events = ujson.loads(recipient_result.content)["events"]
        self.assert_json_success(recipient_result)
        self.assertEqual(len(recipient_events), 2)
        self.assertEqual(recipient_events[0]["type"], "message")
        self.assertEqual(recipient_events[0]["message"]["sender_email"], email)
        self.assertTrue("local_message_id" not in recipient_events[0])
        self.assertEqual(recipient_events[1]["type"], "message")
        self.assertEqual(recipient_events[1]["message"]["sender_email"], email)
        self.assertTrue("local_message_id" not in recipient_events[1])

    def test_get_events_narrow(self):
        email = "hamlet@zulip.com"
        user_profile = get_user_profile_by_email(email)
        self.login(email)

        result = self.tornado_call(get_events_backend, user_profile,
                                   {"apply_markdown": ujson.dumps(True),
                                    "event_types": ujson.dumps(["message"]),
                                    "narrow": ujson.dumps([["stream", "denmark"]]),
                                    "user_client": "website",
                                    "dont_block": ujson.dumps(True),
                                    })
        self.assert_json_success(result)
        queue_id = ujson.loads(result.content)["queue_id"]

        result = self.tornado_call(get_events_backend, user_profile,
                                   {"queue_id": queue_id,
                                    "user_client": "website",
                                    "last_event_id": -1,
                                    "dont_block": ujson.dumps(True),
                                    })
        events = ujson.loads(result.content)["events"]
        self.assert_json_success(result)
        self.assert_length(events, 0, True)

        self.send_message(email, "othello@zulip.com", Recipient.PERSONAL, "hello")
        self.send_message(email, "Denmark", Recipient.STREAM, "hello")

        result = self.tornado_call(get_events_backend, user_profile,
                                   {"queue_id": queue_id,
                                    "user_client": "website",
                                    "last_event_id": -1,
                                    "dont_block": ujson.dumps(True),
                                    })
        events = ujson.loads(result.content)["events"]
        self.assert_json_success(result)
        self.assert_length(events, 1, True)
        self.assertEqual(events[0]["type"], "message")
        self.assertEqual(events[0]["message"]["display_recipient"], "Denmark")

class EventsRegisterTest(AuthedTestCase):
    maxDiff = None
    user_profile = get_user_profile_by_email("hamlet@zulip.com")
    bot = get_user_profile_by_email("welcome-bot@zulip.com")

    def create_bot(self):
        return do_create_user('test-bot@zulip.com', '123',
                              get_realm('zulip.com'), 'Test Bot', 'test',
                              bot=True, bot_owner=self.user_profile)

    def build_update_checker(self, field_name, check):
        return check_dict([
            ('type', equals('realm_bot')),
            ('op', equals('update')),
            ('bot', check_dict([
                ('email', check_string),
                (field_name, check),
            ])),
        ])

    def do_test(self, action, event_types=None):
        client = allocate_client_descriptor(self.user_profile.id, self.user_profile.realm.id,
                                            event_types,
                                            get_client("website"), True, False, 600, [])
        # hybrid_state = initial fetch state + re-applying events triggered by our action
        # normal_state = do action then fetch at the end (the "normal" code path)
        hybrid_state = fetch_initial_state_data(self.user_profile, event_types, "")
        action()
        events = client.event_queue.contents()
        self.assertTrue(len(events) > 0)
        apply_events(hybrid_state, events, self.user_profile)

        normal_state = fetch_initial_state_data(self.user_profile, event_types, "")
        self.match_states(hybrid_state, normal_state)
        return events

    def assert_on_error(self, error):
        if error:
            raise AssertionError(error)

    def match_states(self, state1, state2):
        def normalize(state):
            state['realm_users'] = {u['email']: u for u in state['realm_users']}
            state['subscriptions'] = {u['name']: u for u in state['subscriptions']}
            state['unsubscribed'] = {u['name']: u for u in state['unsubscribed']}
            if 'realm_bots' in state:
                state['realm_bots'] = {u['email']: u for u in state['realm_bots']}
        normalize(state1)
        normalize(state2)
        self.assertEqual(state1, state2)

    def test_send_message_events(self):
        self.do_test(lambda: self.send_message("hamlet@zulip.com", "Verona", Recipient.STREAM, "hello"))

    def test_pointer_events(self):
        self.do_test(lambda: do_update_pointer(self.user_profile, 1500))

    def test_register_events(self):
        self.do_test(lambda: self.register("test1", "test1"))

    def test_alert_words_events(self):
        self.do_test(lambda: do_add_alert_words(self.user_profile, ["alert_word"]))
        self.do_test(lambda: do_remove_alert_words(self.user_profile, ["alert_word"]))

    def test_muted_topics_events(self):
        self.do_test(lambda: do_set_muted_topics(self.user_profile, [["Denmark", "topic"]]))

    def test_change_full_name(self):
        self.do_test(lambda: do_change_full_name(self.user_profile, 'Sir Hamlet'))

    def test_change_realm_name(self):
        self.do_test(lambda: do_set_realm_name(self.user_profile.realm, 'New Realm Name'))

    def test_change_is_admin(self):
        # The first False is probably a noop, then we get transitions in both directions.
        for is_admin in [False, True, False]:
            self.do_test(lambda: do_change_is_admin(self.user_profile, is_admin))

    def test_realm_emoji_events(self):
        self.do_test(lambda: do_add_realm_emoji(get_realm("zulip.com"), "my_emoji",
                                                "https://realm.com/my_emoji"))
        self.do_test(lambda: do_remove_realm_emoji(get_realm("zulip.com"), "my_emoji"))

    def test_realm_filter_events(self):
        self.do_test(lambda: do_add_realm_filter(get_realm("zulip.com"), "#[123]",
                                                "https://realm.com/my_realm_filter/%(id)s"))
        self.do_test(lambda: do_remove_realm_filter(get_realm("zulip.com"), "#[123]"))

    def test_create_bot(self):
        bot_created_checker = check_dict([
            ('type', equals('realm_bot')),
            ('op', equals('add')),
            ('bot', check_dict([
                ('email', check_string),
                ('full_name', check_string),
                ('api_key', check_string),
                ('default_sending_stream', check_none_or(check_string)),
                ('default_events_register_stream', check_none_or(check_string)),
                ('default_all_public_streams', check_bool),
                ('avatar_url', check_string),
            ])),
        ])

        action = lambda: do_create_user('test-bot@zulip.com', '123', get_realm('zulip.com'),
                                        'Test Bot', 'test', bot=True, bot_owner=self.user_profile)
        events = self.do_test(action)
        error = bot_created_checker('events[1]', events[1])
        self.assert_on_error(error)

    def test_change_bot_full_name(self):
        action = lambda: do_change_full_name(self.bot, 'New Bot Name')
        events = self.do_test(action)
        error = self.build_update_checker('full_name', check_string)('events[1]', events[1])
        self.assert_on_error(error)

    def test_regenerate_bot_api_key(self):
        action = lambda: do_regenerate_api_key(self.bot)
        events = self.do_test(action)
        error = self.build_update_checker('api_key', check_string)('events[0]', events[0])
        self.assert_on_error(error)

    def test_rename_stream(self):
        realm = get_realm('zulip.com')
        stream, _ = create_stream_if_needed(realm, 'old_name')
        new_name = u'stream with a brand new name'
        self.subscribe_to_stream(self.user_profile.email, stream.name)

        action = lambda: do_rename_stream(realm, stream.name, new_name)
        events = self.do_test(action)

        schema_checker = check_dict([
            ('type', equals('stream')),
            ('op', equals('update')),
            ('property', equals('email_address')),
            ('value', check_string),
            ('name', equals('old_name')),
        ])
        error = schema_checker('events[0]', events[0])
        self.assert_on_error(error)

        schema_checker = check_dict([
            ('type', equals('stream')),
            ('op', equals('update')),
            ('property', equals('name')),
            ('value', equals(new_name)),
            ('name', equals('old_name')),
        ])
        error = schema_checker('events[1]', events[1])
        self.assert_on_error(error)

    def test_subscribe_events(self):
        subscription_schema_checker = check_list(
            check_dict([
                ('color', check_string),
                ('description', check_string),
                ('email_address', check_string),
                ('invite_only', check_bool),
                ('in_home_view', check_bool),
                ('name', check_string),
                ('desktop_notifications', check_bool),
                ('audible_notifications', check_bool),
                ('stream_id', check_int),
                ('subscribers', check_list(check_int)),
            ])
        )
        add_schema_checker = check_dict([
            ('type', equals('subscription')),
            ('op', equals('add')),
            ('subscriptions', subscription_schema_checker),
        ])
        remove_schema_checker = check_dict([
            ('type', equals('subscription')),
            ('op', equals('remove')),
            ('subscriptions', check_list(
                check_dict([
                    ('name', equals('test_stream')),
                    ('stream_id', check_int),
                ]),
            )),
        ])
        peer_add_schema_checker = check_dict([
            ('type', equals('subscription')),
            ('op', equals('peer_add')),
            ('user_email', check_string),
            ('subscriptions', check_list(check_string)),
        ])
        peer_remove_schema_checker = check_dict([
            ('type', equals('subscription')),
            ('op', equals('peer_remove')),
            ('user_email', check_string),
            ('subscriptions', check_list(check_string)),
        ])
        stream_update_schema_checker = check_dict([
            ('type', equals('stream')),
            ('op', equals('update')),
            ('property', equals('description')),
            ('value', check_string),
            ('name', check_string),
        ])

        action = lambda: self.subscribe_to_stream("hamlet@zulip.com", "test_stream")
        events = self.do_test(action, event_types=["subscription", "realm_user"])
        error = add_schema_checker('events[0]', events[0])
        self.assert_on_error(error)

        action = lambda: self.subscribe_to_stream("othello@zulip.com", "test_stream")
        events = self.do_test(action)
        error = peer_add_schema_checker('events[0]', events[0])
        self.assert_on_error(error)

        stream = get_stream("test_stream", self.user_profile.realm)

        action = lambda: do_remove_subscription(get_user_profile_by_email("othello@zulip.com"), stream)
        events = self.do_test(action)
        error = peer_remove_schema_checker('events[0]', events[0])
        self.assert_on_error(error)

        action = lambda: do_remove_subscription(get_user_profile_by_email("hamlet@zulip.com"), stream)
        events = self.do_test(action)
        error = remove_schema_checker('events[1]', events[1])
        self.assert_on_error(error)

        action = lambda: self.subscribe_to_stream("hamlet@zulip.com", "test_stream")
        events = self.do_test(action)
        error = add_schema_checker('events[1]', events[1])
        self.assert_on_error(error)

        action = lambda: do_change_stream_description(get_realm('zulip.com'), 'test_stream', u'new description')
        events = self.do_test(action)
        error = stream_update_schema_checker('events[0]', events[0])
        self.assert_on_error(error)

from zerver.lib.event_queue import EventQueue
class EventQueueTest(TestCase):
    def test_one_event(self):
        queue = EventQueue("1")
        queue.push({"type": "pointer",
                    "pointer": 1,
                    "timestamp": "1"})
        self.assertFalse(queue.empty())
        self.assertEqual(queue.contents(),
                         [{'id': 0,
                           'type': 'pointer',
                           "pointer": 1,
                           "timestamp": "1"}])

    def test_event_collapsing(self):
        queue = EventQueue("1")
        for pointer_val in xrange(1, 10):
            queue.push({"type": "pointer",
                        "pointer": pointer_val,
                        "timestamp": str(pointer_val)})
        self.assertEqual(queue.contents(),
                         [{'id': 8,
                           'type': 'pointer',
                           "pointer": 9,
                           "timestamp": "9"}])

        queue = EventQueue("2")
        for pointer_val in xrange(1, 10):
            queue.push({"type": "pointer",
                        "pointer": pointer_val,
                        "timestamp": str(pointer_val)})
        queue.push({"type": "unknown"})
        queue.push({"type": "restart", "server_generation": "1"})
        for pointer_val in xrange(11, 20):
            queue.push({"type": "pointer",
                        "pointer": pointer_val,
                        "timestamp": str(pointer_val)})
        queue.push({"type": "restart", "server_generation": "2"})
        self.assertEqual(queue.contents(),
                         [{"type": "unknown",
                           "id": 9,},
                          {'id': 19,
                           'type': 'pointer',
                           "pointer": 19,
                           "timestamp": "19"},
                          {"id": 20,
                           "type": "restart",
                           "server_generation": "2"}])
        for pointer_val in xrange(21, 23):
            queue.push({"type": "pointer",
                        "pointer": pointer_val,
                        "timestamp": str(pointer_val)})
        self.assertEqual(queue.contents(),
                         [{"type": "unknown",
                           "id": 9,},
                          {'id': 19,
                           'type': 'pointer',
                           "pointer": 19,
                           "timestamp": "19"},
                          {"id": 20,
                           "type": "restart",
                           "server_generation": "2"},
                          {'id': 22,
                           'type': 'pointer',
                           "pointer": 22,
                           "timestamp": "22"},
                          ])

    def test_flag_add_collapsing(self):
        queue = EventQueue("1")
        queue.push({"type": "update_message_flags",
                    "flag": "read",
                    "operation": "add",
                    "all": False,
                    "messages": [1, 2, 3, 4],
                    "timestamp": "1"})
        queue.push({"type": "update_message_flags",
                    "flag": "read",
                    "all": False,
                    "operation": "add",
                    "messages": [5, 6],
                    "timestamp": "1"})
        self.assertEqual(queue.contents(),
                         [{'id': 1,
                           'type': 'update_message_flags',
                           "all": False,
                           "flag": "read",
                           "operation": "add",
                           "messages": [1,2,3,4,5,6],
                           "timestamp": "1"}])

    def test_flag_remove_collapsing(self):
        queue = EventQueue("1")
        queue.push({"type": "update_message_flags",
                    "flag": "collapsed",
                    "operation": "remove",
                    "all": False,
                    "messages": [1, 2, 3, 4],
                    "timestamp": "1"})
        queue.push({"type": "update_message_flags",
                    "flag": "collapsed",
                    "all": False,
                    "operation": "remove",
                    "messages": [5, 6],
                    "timestamp": "1"})
        self.assertEqual(queue.contents(),
                         [{'id': 1,
                           'type': 'update_message_flags',
                           "all": False,
                           "flag": "collapsed",
                           "operation": "remove",
                           "messages": [1,2,3,4,5,6],
                           "timestamp": "1"}])

    def test_collapse_event(self):
        queue = EventQueue("1")
        queue.push({"type": "pointer",
                    "pointer": 1,
                    "timestamp": "1"})
        queue.push({"type": "unknown",
                    "timestamp": "1"})
        self.assertEqual(queue.contents(),
                         [{'id': 0,
                           'type': 'pointer',
                           "pointer": 1,
                           "timestamp": "1"},
                          {'id': 1,
                           'type': 'unknown',
                           "timestamp": "1"}])

class TestEventsRegisterAllPublicStreamsDefaults(TestCase):
    def setUp(self):
        self.email = 'hamlet@zulip.com'
        self.user_profile = get_user_profile_by_email(self.email)

    def test_use_passed_all_public_true_default_false(self):
        self.user_profile.default_all_public_streams = False
        self.user_profile.save()
        result = _default_all_public_streams(self.user_profile, True)
        self.assertTrue(result)

    def test_use_passed_all_public_true_default(self):
        self.user_profile.default_all_public_streams = True
        self.user_profile.save()
        result = _default_all_public_streams(self.user_profile, True)
        self.assertTrue(result)

    def test_use_passed_all_public_false_default_false(self):
        self.user_profile.default_all_public_streams = False
        self.user_profile.save()
        result = _default_all_public_streams(self.user_profile, False)
        self.assertFalse(result)

    def test_use_passed_all_public_false_default_true(self):
        self.user_profile.default_all_public_streams = True
        self.user_profile.save()
        result = _default_all_public_streams(self.user_profile, False)
        self.assertFalse(result)

    def test_use_true_default_for_none(self):
        self.user_profile.default_all_public_streams = True
        self.user_profile.save()
        result = _default_all_public_streams(self.user_profile, None)
        self.assertTrue(result)

    def test_use_false_default_for_none(self):
        self.user_profile.default_all_public_streams = False
        self.user_profile.save()
        result = _default_all_public_streams(self.user_profile, None)
        self.assertFalse(result)

class TestEventsRegisterNarrowDefaults(TestCase):
    def setUp(self):
        self.email = 'hamlet@zulip.com'
        self.user_profile = get_user_profile_by_email(self.email)
        self.stream = get_stream('Verona', self.user_profile.realm)

    def test_use_passed_narrow_no_default(self):
        self.user_profile.default_events_register_stream_id = None
        self.user_profile.save()
        result = _default_narrow(self.user_profile, [('stream', 'my_stream')])
        self.assertEqual(result, [('stream', 'my_stream')])

    def test_use_passed_narrow_with_default(self):
        self.user_profile.default_events_register_stream_id = self.stream.id
        self.user_profile.save()
        result = _default_narrow(self.user_profile, [('stream', 'my_stream')])
        self.assertEqual(result, [('stream', 'my_stream')])

    def test_use_default_if_narrow_is_empty(self):
        self.user_profile.default_events_register_stream_id = self.stream.id
        self.user_profile.save()
        result = _default_narrow(self.user_profile, [])
        self.assertEqual(result, [('stream', 'Verona')])

    def test_use_narrow_if_default_is_none(self):
        self.user_profile.default_events_register_stream_id = None
        self.user_profile.save()
        result = _default_narrow(self.user_profile, [])
        self.assertEqual(result, [])
