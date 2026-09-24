"""Offline claim/exit regression. Uses simulated screens and a virtual clock.

The supplied image crop is separately exercised with real Vision in
validate_video.py. No test in this file connects to MuMu or sends real input.
"""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import collector as module
from collector import Collector, Halt
from vision import Match, Screen, LABELS


def matched(name, point=(774, 500)):
    return Match(name, .99, 0, point)


class Clock:
    now = 0
    def monotonic(self):
        return self.now


class Device:
    def __init__(self, stop, clock, *, post=None, initially_empty=False, lost_backs=0,
                 reward_frames=0, stop_after_claim=False, app_change=False, back_to="menu",
                 initial_modes=None, wake_after=1, wake_to="menu", stop_after_wake=False):
        self.stop, self.clock = stop, clock
        self.post = post or {}
        self.initially_empty, self.lost_backs = initially_empty, lost_backs
        self.reward_frames, self.overlay_left = reward_frames, 0
        self.stop_after_claim, self.app_change = stop_after_claim, app_change
        self.back_to, self.state = back_to, "menu"
        self.claims = {room: 0 for room in LABELS}
        self.backs = {room: 0 for room in LABELS}
        self.actions, self.frames = [], []
        self.initial_modes = initial_modes or {}
        self.room_reads = {room: 0 for room in LABELS}
        self.wake_after, self.wake_to, self.stop_after_wake = wake_after, wake_to, stop_after_wake
        self.swipes = []

    def capture(self):
        self.clock.now += .1
        if self.app_change and any(self.claims.values()):
            raise Halt("현재 앱이 달라졌습니다")
        if self.overlay_left:
            self.overlay_left -= 1
            screen = Screen("reward", {"reward": matched("reward")})
        elif self.state == "menu":
            screen = Screen("menu", {"menu_"+room: matched("menu_"+room, (x, 270))
                                     for room, x in zip(LABELS, (900, 839, 780))})
        elif self.state == "main":
            screen = Screen("main", {"main_menu": matched("main_menu", (915, 28))})
        elif self.state == "sleep":
            screen = Screen("sleep", {})
        elif self.state == "unknown":
            screen = Screen("unknown", {})
        else:
            room = self.state
            mode = (self.post.get(room, "empty") if self.claims[room]
                    else self.initial_modes.get(room,"empty" if self.initially_empty else "ready"))
            if isinstance(mode, (list, tuple)):
                index = self.claims[room]-1 if self.claims[room] else self.room_reads[room]
                mode = mode[min(index, len(mode)-1)]
            self.room_reads[room] += 1
            if mode == "alternating":
                mode = "ready" if len(self.frames) % 2 else "empty"
            matches = {"room_"+room: matched("room_"+room)}
            state = room+"_"+mode
            if mode in {"empty", "ready"}:
                matches[mode+"_"+room] = matched(mode+"_"+room)
            elif mode == "ready_only":
                state, matches = "unknown", {"ready_"+room: matched("ready_"+room)}
            elif mode == "button_only":
                state, matches = "unknown", {"empty_"+room: matched("empty_"+room)}
            elif mode == "both":
                state = room+"_wait"
                matches.update({kind+room: matched(kind+room) for kind in ("ready_", "empty_")})
            elif mode == "unknown":
                state, matches = "unknown", {}
            elif mode == "wrong_room":
                state = "wood_ready"
                matches = {"room_wood": matched("room_wood"), "ready_wood": matched("ready_wood"),
                           "empty_farm": matched("empty_farm")}
            screen = Screen(state, matches)
        self.frames.append(screen)
        return screen

    def drag(self, start, end):
        assert self.state == "sleep"
        assert not self.stop.is_set()
        assert 398 <= start[0] <= 426 and 455 <= start[1] <= 483
        assert end[0] >= 585 and end[1] == start[1]
        self.swipes.append((start,end))
        self.actions.append("wake")
        if len(self.swipes) >= self.wake_after:
            self.state = self.wake_to
        if self.stop_after_wake:
            self.stop.set()

    def click(self, point):
        assert not self.stop.is_set(), "No click after cancellation"
        assert self.frames[-1].state != "reward", "No claim or back click through a reward overlay"
        x, y = point
        if self.state == "menu":
            if y > 450:
                self.state = "sleep"
                self.actions.append("sleep")
            else:
                self.state = "farm" if x > 880 else "wood" if x > 810 else "mine"
                self.actions.append("open_"+self.state)
        elif self.state == "main":
            assert 900 < x < 935
            self.actions.append("open_menu")
            self.state = "menu"
        elif x < 80 and y < 60:
            room = self.state
            self.backs[room] += 1
            self.actions.append("back_"+room)
            if self.backs[room] > self.lost_backs:
                self.state = self.back_to
        else:
            assert 690 < x < 860 and 475 < y < 525
            self.claims[self.state] += 1
            self.actions.append("claim_"+self.state)
            self.overlay_left = self.reward_frames
            if self.stop_after_claim:
                self.stop.set()


class CollectionRegression(unittest.TestCase):
    def run_flow(self, **settings):
        clock, stop = Clock(), threading.Event()
        device = Device(stop, clock, **settings)
        seen = []
        collector = Collector(device, SimpleNamespace(recognize=lambda frame: frame), stop,
                              lambda text: None, on_result=lambda room, result: seen.append((room, result)))
        def pause(seconds):
            if stop.is_set():
                raise Halt("Stopped")
            clock.now += seconds
        collector.pause = pause
        return collector, device, clock, seen

    def cycle(self, collector, clock, rooms=None):
        with patch.object(module, "time", SimpleNamespace(monotonic=clock.monotonic)):
            return collector.cycle(rooms or list(LABELS))

    def test_first_success_skips_remaining_claims_and_visits_next_facility(self):
        c, d, clock, seen = self.run_flow()
        self.assertEqual(self.cycle(c, clock), dict.fromkeys(LABELS, "collected"))
        self.assertEqual(d.claims, dict.fromkeys(LABELS, 1))
        self.assertEqual(seen, [(room, "collected") for room in LABELS])
        self.assertEqual(d.actions, [action for room in LABELS
                                    for action in ["open_"+room,"claim_"+room,"back_"+room]])

    def test_initially_disabled_buttons_are_skipped_without_claims(self):
        c, d, clock, _ = self.run_flow(initially_empty=True)
        self.assertEqual(self.cycle(c, clock), dict.fromkeys(LABELS, "skipped"))
        self.assertEqual(d.claims, dict.fromkeys(LABELS, 0))
        self.assertEqual(c.claim_counts, dict.fromkeys(LABELS, 0))
        self.assertEqual(d.actions, [action for room in LABELS for action in ("open_"+room,"back_"+room)])

    def test_unreadable_button_on_entry_is_deferred_without_blocking_other_rooms(self):
        c, d, clock, seen = self.run_flow(initial_modes={"farm":"wait"})
        issues=[]
        c.on_issue=lambda room,reason:issues.append((room,reason,c.last_screen.state))
        self.assertEqual(self.cycle(c,clock),{"farm":"unrecognized","wood":"collected","mine":"collected"})
        self.assertEqual(d.claims,{"farm":0,"wood":1,"mine":1})
        self.assertEqual(d.room_reads['farm'],7)
        self.assertEqual(seen[0],("farm","unrecognized"))
        self.assertEqual(issues[0][0],"farm")
        self.assertEqual(issues[0][2],"farm_wait")
        self.assertLess(clock.now,20)

    def test_temporarily_unreadable_empty_button_is_rechecked_then_skipped(self):
        c,d,clock,_=self.run_flow(initial_modes={"farm":["wait","wait","empty"]})
        self.assertEqual(self.cycle(c,clock)["farm"],"skipped")
        self.assertEqual(d.claims["farm"],0)
        self.assertEqual(d.room_reads["farm"],5)

    def test_temporarily_unreadable_ready_button_is_rechecked_then_claimed(self):
        c,d,clock,_=self.run_flow(initial_modes={"farm":["wait","wait","ready"]})
        self.assertEqual(self.cycle(c,clock)["farm"],"collected")
        self.assertEqual(d.claims["farm"],1)

    def test_stat_effect_before_claim_is_reobserved_without_duplicate_tap(self):
        c,d,clock,_=self.run_flow(initial_modes={'wood':['ready','ready','ready_only','ready','ready']})
        self.assertEqual(self.cycle(c,clock)['wood'],'collected')
        self.assertEqual(d.claims['wood'],1)

    def test_empty_after_preinput_change_is_not_reported_as_our_claim(self):
        c,d,clock,_=self.run_flow(initial_modes={'wood':['ready','ready','empty']})
        self.assertEqual(self.cycle(c,clock)['wood'],'skipped')
        self.assertEqual(d.claims['wood'],0)

    def test_persistent_effect_does_not_trigger_unverified_claim(self):
        c,d,clock,_=self.run_flow(initial_modes={'wood':['ready','ready','ready_only']})
        self.assertEqual(self.cycle(c,clock)['wood'],'failed')
        self.assertEqual(d.claims['wood'],0)

    def test_missing_back_after_deferred_button_still_stops_at_verified_room(self):
        c,d,clock,seen=self.run_flow(initial_modes={"farm":"wait"},lost_backs=99)
        with self.assertRaisesRegex(Halt,"뒤로가기를 3회"):
            self.cycle(c,clock)
        self.assertEqual(seen,[("farm","unrecognized")])
        self.assertNotIn("open_wood",d.actions)

    def test_sleep_drag_retries_only_while_sleep_is_confirmed(self):
        for needed in (1,2,3):
            with self.subTest(attempts=needed):
                c,d,clock,_=self.run_flow(wake_after=needed)
                d.state="sleep"
                self.assertEqual(self.cycle(c,clock),dict.fromkeys(LABELS,"collected"))
                self.assertEqual(len(d.swipes),needed)
                self.assertEqual(c.wake_attempts,needed)

    def test_three_failed_drags_stop_without_opening_any_facility(self):
        c,d,clock,_=self.run_flow(wake_after=99)
        d.state="sleep"
        with self.assertRaisesRegex(Halt,"절전 해제를 3회"):
            self.cycle(c,clock)
        self.assertEqual(d.actions,["wake"]*3)

    def test_unknown_after_wake_does_not_receive_another_drag(self):
        c,d,clock,_=self.run_flow(wake_to="unknown")
        d.state="sleep"
        with self.assertRaises(Halt):
            self.cycle(c,clock)
        self.assertEqual(d.actions,["wake"])

    def test_stop_after_first_drag_prevents_wake_retry(self):
        c,d,clock,_=self.run_flow(wake_after=99,stop_after_wake=True)
        d.state="sleep"
        with self.assertRaises(Halt):
            self.cycle(c,clock)
        self.assertEqual(d.actions,["wake"])

    def test_second_success_skips_third_claim(self):
        c, d, clock, seen = self.run_flow(post={"farm": ["ready", "empty"]})
        self.assertEqual(self.cycle(c, clock), dict.fromkeys(LABELS, "collected"))
        self.assertEqual(d.claims, {"farm": 2, "wood": 1, "mine": 1})
        self.assertEqual(seen.count(("farm", "collected")), 1)

    def test_third_attempt_can_complete_without_exceeding_limit(self):
        c, d, clock, _ = self.run_flow(post={"farm": ["ready", "ready", "empty"]})
        self.assertEqual(self.cycle(c, clock), dict.fromkeys(LABELS, "collected"))
        self.assertEqual(d.claims, {"farm": 3, "wood": 1, "mine": 1})

    def test_ambiguous_button_is_not_treated_as_disabled(self):
        c, d, clock, _ = self.run_flow(post={"farm": ["both", "empty"]})
        self.assertEqual(self.cycle(c, clock)["farm"], "failed")
        self.assertEqual(d.claims["farm"], 1)

    def test_all_facilities_retry_independently_until_success(self):
        c, d, clock, _ = self.run_flow(post={"wood": ["ready", "empty"],
                                            "mine": ["ready", "ready", "empty"]})
        self.assertEqual(self.cycle(c, clock), dict.fromkeys(LABELS, "collected"))
        self.assertEqual(d.claims, {"farm": 1, "wood": 2, "mine": 3})

    def test_still_active_after_three_clicks_continues_without_false_success(self):
        c, d, clock, _ = self.run_flow(post={"farm": "ready"})
        result = self.cycle(c, clock)
        self.assertEqual(result, {"farm": "attempted", "wood": "collected", "mine": "collected"})
        self.assertEqual(d.claims, {"farm": 3, "wood": 1, "mine": 1})
        self.assertEqual(d.state, "menu")

    def test_unreadable_button_on_known_page_does_not_block_departure(self):
        c, d, clock, _ = self.run_flow(post={"farm": "wait"})
        result = self.cycle(c, clock)
        self.assertEqual(result["farm"], "attempted")
        self.assertEqual(d.claims, dict.fromkeys(LABELS, 1))
        self.assertEqual(d.state, "menu")

    def test_resource_button_alone_after_claim_can_confirm_page(self):
        c, d, clock, _ = self.run_flow(post={"farm": "button_only"})
        self.assertEqual(self.cycle(c, clock), dict.fromkeys(LABELS, "collected"))
        self.assertEqual(d.claims["farm"], 1)

    def test_both_button_variants_matching_blocks_repeated_input(self):
        c, d, clock, _ = self.run_flow(post={"farm": "both"})
        self.assertEqual(self.cycle(c, clock)["farm"], "failed")
        self.assertEqual(d.claims["farm"], 1)
        self.assertEqual(d.state, "menu")

    def test_button_animation_does_not_reset_page_confirmation(self):
        c, d, clock, _ = self.run_flow(post={"farm": "alternating"})
        result=self.cycle(c, clock)
        self.assertEqual(d.claims["farm"], 1)
        self.assertEqual(result["farm"],"failed")
        self.assertEqual(d.state,"menu")
        self.assertLess(clock.now, 20)

    def test_reward_overlay_finishes_before_reclick_or_back(self):
        c, d, clock, _ = self.run_flow(reward_frames=8)
        self.assertEqual(self.cycle(c, clock), dict.fromkeys(LABELS, "collected"))
        self.assertTrue(any(frame.state == "reward" for frame in d.frames))

    def test_dropped_back_clicks_are_retried_on_the_same_page(self):
        c, d, clock, _ = self.run_flow(lost_backs=2)
        self.assertEqual(self.cycle(c, clock), dict.fromkeys(LABELS, "collected"))
        self.assertEqual(d.backs, dict.fromkeys(LABELS, 3))

    def test_failed_departure_keeps_completed_result_and_stops_after_three_backs(self):
        c, d, clock, seen = self.run_flow(lost_backs=99)
        with self.assertRaisesRegex(Halt, "뒤로가기를 3회"):
            self.cycle(c, clock)
        self.assertEqual(c.results, {"farm": "collected"})
        self.assertEqual(seen, [("farm", "collected")])
        self.assertEqual(d.backs["farm"], 3)
        self.assertNotIn("open_wood", d.actions)

    def test_return_to_main_reopens_menu_before_next_facility(self):
        c, d, clock, _ = self.run_flow(back_to="main")
        self.cycle(c, clock)
        self.assertEqual(d.actions.count("open_menu"), 3)

    def test_unknown_screen_after_claim_does_not_receive_guess_clicks(self):
        c, d, clock, _ = self.run_flow(post={"farm": "unknown"})
        with self.assertRaises(Halt):
            self.cycle(c, clock)
        self.assertEqual(d.actions, ["open_farm", "claim_farm"])
        self.assertLess(clock.now, 25)

    def test_other_facility_blocks_repeat_even_if_farm_button_also_matches(self):
        c, d, clock, _ = self.run_flow(post={"farm": "wrong_room"})
        with self.assertRaises(Halt):
            self.cycle(c, clock)
        self.assertEqual(d.actions, ["open_farm", "claim_farm"])

    def test_manual_stop_cancels_remaining_claims_and_navigation(self):
        c, d, clock, _ = self.run_flow(stop_after_claim=True)
        with self.assertRaises(Halt):
            self.cycle(c, clock)
        self.assertEqual(d.actions, ["open_farm", "claim_farm"])

    def test_app_change_prevents_another_claim(self):
        c, d, clock, _ = self.run_flow(app_change=True)
        with self.assertRaisesRegex(Halt, "현재 앱"):
            self.cycle(c, clock)
        self.assertEqual(d.actions, ["open_farm", "claim_farm"])


if __name__ == "__main__":
    unittest.main()
