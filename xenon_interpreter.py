#!/usr/bin/env python

import argparse
import os
import pyparsing as pp
import sys
import types

# This is so that we can use the same fully qualified names in this script as
# in the rest of the code, which is designed so that py.test can correctly
# import modules.
sys.path.append(os.pardir)

import xenon.base.exceptions as xe
from xenon.base.commands import *
from xenon.base.command_bindings import getParser, getCommandClass
from xenon.base.datatypes import *
import xenon.generators

DEBUG = False

class XenonInterpreter():
  """ Executes a Xenon file.

  The result of the execution is a DesignSweep object, which can then be passed
  to a ConfigGenerator object to expand the design sweep into each configuration.
  This result can be accessible through the XenonInterpreter.configured_sweep
  attribute.
  """
  def __init__(self, filename, test_mode=False, stream=sys.stdout):
    self.filename = filename
    # List of (line_number, ParseResult) tuples.
    self.commands_ = []
    # Parser object for the complete line.
    self.line_parser_ = buildCommandParser()
    self.test_mode = test_mode
    # Where to print debugging information.
    self.stream = stream

  def handleXenonCommandError(self, command, err):
    msg = "On line %d: %s\n" % (command.lineno, command.line)
    msg += "%s: %s\n" % (err.__class__.__name__, str(err))
    sys.stderr.write(msg)
    sys.exit(1)

  def handleGeneratorError(self, target, err):
    """ Handle certain exceptions thrown during generation.

    TODO: This isn't a great mechanism. Redo.
    """
    msg = "Error occurred in generating %s\n" % target
    if isinstance(err, ImportError):
      msg += "The generator module generator_%s was not found.\n" % target
    elif isinstance(err, AttributeError):
      msg += "Do you have a generator for target %s?\n" % target
    msg += "%s: %s\n" % (err.__class__.__name__, str(err))
    sys.stderr.write(msg)
    sys.exit(1)

  def handleSyntaxError(self, parser_err, line_number):
    spaces =  ' ' * (parser_err.col - 1)
    msg = "Invalid syntax on line %s:\n" % line_number
    msg += "  %s\n" % parser_err.line
    msg += "  %s^\n" % spaces
    msg += "  %s\n" % str(parser_err)
    sys.stderr.write(msg)
    sys.exit(1)

  def parse(self):
    with open(self.filename) as f:
      for line_number, line in enumerate(f):
        line_number += 1  # Line numbers aren't zero indexed.
        line = line.strip()
        if not line:
          continue
        # Determine if this line begins with a valid command or not.
        result = None
        try:
          result = self.line_parser_.parseString(line, parseAll=True)
          if result.command == "":
            continue
        except pp.ParseException as x:
          self.handleSyntaxError(x, line_number)

        # If so, parse the rest of the line.
        line_command = result.command
        try:
          # Reform the line without the comments.
          line = result.command + ' ' + ' '.join(result.rest[0])
          result = getParser(result.command).parseString(line, parseAll=True)
        except pp.ParseException as x:
          self.handleSyntaxError(x, line_number)

        commandClass = getCommandClass(line_command)(line_number, line, result)
        self.commands_.append(commandClass)

  def execute(self):
    current_sweep = DesignSweep()
    for command in self.commands_:
      if DEBUG:
        self.stream.write(command.line + "\n")
      try:
        command(current_sweep)
      except xe.XenonError as e:
        self.handleXenonCommandError(command, e)

      if current_sweep.done:
        if DEBUG:
          self.stream.write("Configured sweep:\n")
          current_sweep.dump(stream=self.stream)
        self.generate_outputs(current_sweep)
        current_sweep = DesignSweep()

  def generate_outputs(self, sweep):
    for output in sweep.generate_outputs:
      generator_module = self.get_generator_module(output)
      try:
        generator = generator_module.get_generator(sweep)
      except AttributeError as e:
        self.handleGeneratorError(output, e)

      try:
        generated_configs = generator.generate()
      except xe.XenonError as e:
        self.handleConfigGeneratorError(output, e)

      if self.test_mode:
        for config in generated_configs:
          config.dump(stream=self.stream)

  def run(self):
    self.parse()
    self.execute()

  def get_generator_module(self, generate_target):
    """ Returns the module named generator_[generate_target].

    This module must be under xenon.generators. If such a module does not
    exist, then None is returned.
    """
    module_name = "generator_%s" % generate_target
    try:
      module = importlib.import_module(".".join(["xenon", "generators", module_name]))
    except ImportError as e:
      self.handleGeneratorError(generate_target, e)
    return module

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("xenon_file", help="Xenon input file.")
  parser.add_argument("-d", "--debug", action="store_true", help="Turn on debugging output.")
  parser.add_argument("-t", "--test", action="store_true", help="Testing mode.")
  args = parser.parse_args()

  global DEBUG
  DEBUG = args.debug
  interpreter = XenonInterpreter(args.xenon_file, test_mode=args.test)
  interpreter.run()

if __name__ == "__main__":
  main()
