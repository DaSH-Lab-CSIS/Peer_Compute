# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
    name: recap_tasks
    type: stdout
    short_description: Default Ansible output plus per-host task list after PLAY RECAP
    description:
      - Subclasses the built-in default stdout callback.
      - After the normal PLAY RECAP block, prints TASK RECAP with one line per task
        executed per host (ok, changed, failed, skipped, unreachable).
    version_added: "1.0"
    extends_documentation_fragment:
      - default_callback
      - result_format_callback
"""

from collections import defaultdict

from ansible import constants as C
from ansible.playbook.task_include import TaskInclude
from ansible.plugins.callback.default import CallbackModule as DefaultCallbackModule


class CallbackModule(DefaultCallbackModule):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "stdout"
    CALLBACK_NAME = "recap_tasks"

    def __init__(self):
        super().__init__()
        self._recap_by_host = defaultdict(list)

    def _recap_append(self, host, status, task_label):
        self._recap_by_host[host].append((status, task_label))

    def _item_suffix(self, item_dict):
        try:
            label = self._get_item_label(item_dict)
        except Exception:
            label = item_dict.get("item", "")
        if label is None or label == "":
            return ""
        return " (item=%s)" % label

    def _record_loop_results(self, result, host, name):
        for item in result._result.get("results") or []:
            if item.get("skipped"):
                st = "skipped"
            elif item.get("failed") or item.get("exception"):
                st = "failed"
            elif item.get("unreachable"):
                st = "unreachable"
            elif item.get("changed"):
                st = "changed"
            else:
                st = "ok"
            self._recap_append(host, st, name + self._item_suffix(item))

    def _record_ok(self, result):
        if isinstance(result._task, TaskInclude):
            return
        host = result._host.get_name()
        name = result._task.get_name().strip()
        if result._task.loop and "results" in result._result:
            self._record_loop_results(result, host, name)
            return
        st = "changed" if result.is_changed() else "ok"
        self._recap_append(host, st, name)

    def _record_failed(self, result):
        if isinstance(result._task, TaskInclude):
            return
        host = result._host.get_name()
        name = result._task.get_name().strip()
        if result._task.loop and "results" in result._result:
            self._record_loop_results(result, host, name)
            return
        self._recap_append(host, "failed", name)

    def _record_skipped(self, result):
        if isinstance(result._task, TaskInclude):
            return
        host = result._host.get_name()
        name = result._task.get_name().strip()
        if result._task.loop and "results" in result._result:
            self._record_loop_results(result, host, name)
            return
        self._recap_append(host, "skipped", name)

    def _record_unreachable(self, result):
        if isinstance(result._task, TaskInclude):
            return
        host = result._host.get_name()
        name = result._task.get_name().strip()
        self._recap_append(host, "unreachable", name)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._record_failed(result)
        super().v2_runner_on_failed(result, ignore_errors=ignore_errors)

    def v2_runner_on_ok(self, result):
        self._record_ok(result)
        super().v2_runner_on_ok(result)

    def v2_runner_on_skipped(self, result):
        self._record_skipped(result)
        super().v2_runner_on_skipped(result)

    def v2_runner_on_unreachable(self, result):
        self._record_unreachable(result)
        super().v2_runner_on_unreachable(result)

    def v2_playbook_on_stats(self, stats):
        super().v2_playbook_on_stats(stats)
        if not self._recap_by_host:
            return

        self._display.banner("TASK RECAP (by host)")

        for host in sorted(self._recap_by_host.keys()):
            entries = self._recap_by_host[host]
            if not entries:
                continue
            self._display.display("  %s" % host, screen_only=True)
            self._display.display("  %s" % host, log_only=True)
            for status, label in entries:
                color = {
                    "ok": C.COLOR_OK,
                    "changed": C.COLOR_CHANGED,
                    "failed": C.COLOR_ERROR,
                    "skipped": C.COLOR_SKIP,
                    "unreachable": C.COLOR_UNREACHABLE,
                }.get(status, C.COLOR_VERBOSE)
                line_screen = "    %s: %s" % (status, label)
                self._display.display(line_screen, color=color, screen_only=True)
                self._display.display(line_screen, log_only=True)

        self._display.display("", screen_only=True)
