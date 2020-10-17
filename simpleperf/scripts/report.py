#!/usr/bin/env python
#
# Copyright (C) 2015 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Simpleperf gui reporter: provide gui interface for simpleperf report command.

There are two ways to use gui reporter. One way is to pass it a report file
generated by simpleperf report command, and reporter will display it. The
other ways is to pass it any arguments you want to use when calling
simpleperf report command. The reporter will call `simpleperf report` to
generate report file, and display it.
"""

import os
import os.path
import re
import subprocess
import sys

try:
    from tkinter import *
    from tkinter.font import Font
    from tkinter.ttk import *
except ImportError:
    from Tkinter import *
    from tkFont import Font
    from ttk import *

from simpleperf_utils import *

PAD_X = 3
PAD_Y = 3


class CallTreeNode(object):

  """Representing a node in call-graph."""

  def __init__(self, percentage, function_name):
    self.percentage = percentage
    self.call_stack = [function_name]
    self.children = []

  def add_call(self, function_name):
    self.call_stack.append(function_name)

  def add_child(self, node):
    self.children.append(node)

  def __str__(self):
    strs = self.dump()
    return '\n'.join(strs)

  def dump(self):
    strs = []
    strs.append('CallTreeNode percentage = %.2f' % self.percentage)
    for function_name in self.call_stack:
      strs.append(' %s' % function_name)
    for child in self.children:
      child_strs = child.dump()
      strs.extend(['  ' + x for x in child_strs])
    return strs


class ReportItem(object):

  """Representing one item in report, may contain a CallTree."""

  def __init__(self, raw_line):
    self.raw_line = raw_line
    self.call_tree = None

  def __str__(self):
    strs = []
    strs.append('ReportItem (raw_line %s)' % self.raw_line)
    if self.call_tree is not None:
      strs.append('%s' % self.call_tree)
    return '\n'.join(strs)

class EventReport(object):

  """Representing report for one event attr."""

  def __init__(self, common_report_context):
    self.context = common_report_context[:]
    self.title_line = None
    self.report_items = []


def parse_event_reports(lines):
  # Parse common report context
  common_report_context = []
  line_id = 0
  while line_id < len(lines):
    line = lines[line_id]
    if not line or line.find('Event:') == 0:
      break
    common_report_context.append(line)
    line_id += 1

  event_reports = []
  in_report_context = True
  cur_event_report = EventReport(common_report_context)
  cur_report_item = None
  call_tree_stack = {}
  vertical_columns = []
  last_node = None

  has_skipped_callgraph = False

  for line in lines[line_id:]:
    if not line:
      in_report_context = not in_report_context
      if in_report_context:
        cur_event_report = EventReport(common_report_context)
      continue

    if in_report_context:
      cur_event_report.context.append(line)
      if line.find('Event:') == 0:
        event_reports.append(cur_event_report)
      continue

    if cur_event_report.title_line is None:
      cur_event_report.title_line = line
    elif not line[0].isspace():
      cur_report_item = ReportItem(line)
      cur_event_report.report_items.append(cur_report_item)
      # Each report item can have different column depths.
      vertical_columns = []
    else:
      for i in range(len(line)):
        if line[i] == '|':
          if not vertical_columns or vertical_columns[-1] < i:
            vertical_columns.append(i)

      if not line.strip('| \t'):
        continue
      if 'skipped in brief callgraph mode' in line:
        has_skipped_callgraph = True
        continue

      if line.find('-') == -1:
        line = line.strip('| \t')
        function_name = line
        last_node.add_call(function_name)
      else:
        pos = line.find('-')
        depth = -1
        for i in range(len(vertical_columns)):
          if pos >= vertical_columns[i]:
            depth = i
        assert depth != -1

        line = line.strip('|- \t')
        m = re.search(r'^([\d\.]+)%[-\s]+(.+)$', line)
        if m:
          percentage = float(m.group(1))
          function_name = m.group(2)
        else:
          percentage = 100.0
          function_name = line

        node = CallTreeNode(percentage, function_name)
        if depth == 0:
          cur_report_item.call_tree = node
        else:
          call_tree_stack[depth - 1].add_child(node)
        call_tree_stack[depth] = node
        last_node = node

  if has_skipped_callgraph:
      log_warning('some callgraphs are skipped in brief callgraph mode')

  return event_reports


class ReportWindow(object):

  """A window used to display report file."""

  def __init__(self, main, report_context, title_line, report_items):
    frame = Frame(main)
    frame.pack(fill=BOTH, expand=1)

    font = Font(family='courier', size=12)

    # Report Context
    for line in report_context:
      label = Label(frame, text=line, font=font)
      label.pack(anchor=W, padx=PAD_X, pady=PAD_Y)

    # Space
    label = Label(frame, text='', font=font)
    label.pack(anchor=W, padx=PAD_X, pady=PAD_Y)

    # Title
    label = Label(frame, text='  ' + title_line, font=font)
    label.pack(anchor=W, padx=PAD_X, pady=PAD_Y)

    # Report Items
    report_frame = Frame(frame)
    report_frame.pack(fill=BOTH, expand=1)

    yscrollbar = Scrollbar(report_frame)
    yscrollbar.pack(side=RIGHT, fill=Y)
    xscrollbar = Scrollbar(report_frame, orient=HORIZONTAL)
    xscrollbar.pack(side=BOTTOM, fill=X)

    tree = Treeview(report_frame, columns=[title_line], show='')
    tree.pack(side=LEFT, fill=BOTH, expand=1)
    tree.tag_configure('set_font', font=font)

    tree.config(yscrollcommand=yscrollbar.set)
    yscrollbar.config(command=tree.yview)
    tree.config(xscrollcommand=xscrollbar.set)
    xscrollbar.config(command=tree.xview)

    self.display_report_items(tree, report_items)

  def display_report_items(self, tree, report_items):
    for report_item in report_items:
      prefix_str = '+ ' if report_item.call_tree is not None else '  '
      id = tree.insert(
          '',
          'end',
          None,
          values=[
              prefix_str +
              report_item.raw_line],
          tag='set_font')
      if report_item.call_tree is not None:
        self.display_call_tree(tree, id, report_item.call_tree, 1)

  def display_call_tree(self, tree, parent_id, node, indent):
    id = parent_id
    indent_str = '    ' * indent

    if node.percentage != 100.0:
      percentage_str = '%.2f%% ' % node.percentage
    else:
      percentage_str = ''

    for i in range(len(node.call_stack)):
      s = indent_str
      s += '+ ' if node.children and i == len(node.call_stack) - 1 else '  '
      s += percentage_str if i == 0 else ' ' * len(percentage_str)
      s += node.call_stack[i]
      child_open = False if i == len(node.call_stack) - 1 and indent > 1 else True
      id = tree.insert(id, 'end', None, values=[s], open=child_open,
                       tag='set_font')

    for child in node.children:
      self.display_call_tree(tree, id, child, indent + 1)


def display_report_file(report_file, self_kill_after_sec):
    fh = open(report_file, 'r')
    lines = fh.readlines()
    fh.close()

    lines = [x.rstrip() for x in lines]
    event_reports = parse_event_reports(lines)

    if event_reports:
        root = Tk()
        for i in range(len(event_reports)):
            report = event_reports[i]
            parent = root if i == 0 else Toplevel(root)
            ReportWindow(parent, report.context, report.title_line, report.report_items)
        if self_kill_after_sec:
            root.after(self_kill_after_sec * 1000, lambda: root.destroy())
        root.mainloop()


def call_simpleperf_report(args, show_gui, self_kill_after_sec):
    simpleperf_path = get_host_binary_path('simpleperf')
    if not show_gui:
        subprocess.check_call([simpleperf_path, 'report'] + args)
    else:
        report_file = 'perf.report'
        subprocess.check_call([simpleperf_path, 'report', '--full-callgraph'] + args +
                              ['-o', report_file])
        display_report_file(report_file, self_kill_after_sec=self_kill_after_sec)


def get_simpleperf_report_help_msg():
    simpleperf_path = get_host_binary_path('simpleperf')
    args = [simpleperf_path, 'report', '-h']
    proc = subprocess.Popen(args, stdout=subprocess.PIPE)
    (stdoutdata, _) = proc.communicate()
    stdoutdata = bytes_to_str(stdoutdata)
    return stdoutdata[stdoutdata.find('\n') + 1:]


def main():
    self_kill_after_sec = 0
    args = sys.argv[1:]
    if args and args[0] == "--self-kill-for-testing":
        self_kill_after_sec = 1
        args = args[1:]
    if len(args) == 1 and os.path.isfile(args[0]):
        display_report_file(args[0], self_kill_after_sec=self_kill_after_sec)

    i = 0
    args_for_report_cmd = []
    show_gui = False
    while i < len(args):
        if args[i] == '-h' or args[i] == '--help':
            print('report.py   A python wrapper for simpleperf report command.')
            print('Options supported by simpleperf report command:')
            print(get_simpleperf_report_help_msg())
            print('\nOptions supported by report.py:')
            print('--gui   Show report result in a gui window.')
            print('\nIt also supports showing a report generated by simpleperf report cmd:')
            print('\n  python report.py report_file')
            sys.exit(0)
        elif args[i] == '--gui':
            show_gui = True
            i += 1
        else:
            args_for_report_cmd.append(args[i])
            i += 1

    call_simpleperf_report(args_for_report_cmd, show_gui, self_kill_after_sec)


if __name__ == '__main__':
    main()
