"""Utilities for building contextual functions.

The MachineController has a lot of functions which take the same arguments,
many of which are contextual.  Avoiding respecifying these arguments every time
will lead to cleaner and clearer code.  For example:

    with controller(app_id=32):
        with controller(x=1, y=1):
            controller.do_something(...)

        with controller(x=2, y=2):
            controller.do_something(...)

Is arguably clearer and less prone to silly mistakes than:

    controller.do_something(x=1, y=1, app_id=32)
    controller.do_something(x=2, y=2, app_id=32)

This module provides decorators for functions so that they can use contextual
arguments and a mixin for classes that provides a `get_new_context` method
which could be mapped to `__call__` to produce and use concepts as in the
previous example.
"""
import collections
import inspect
import sentinel
from six import iteritems


# Allow specifying keyword arguments as required, i.e., they must be satisfied
# by either the context OR by the caller.
Required = sentinel.create('Required')


class ContextMixin(object):
    """A mix-in which provides a context stack and allows querying of the stack
    to form keyword arguments.
    """
    def __init__(self, initial_context={}):
        """Create a context stack for this object.

        Parameters
        ----------
        initial_context : {kwarg: value}
            An initial set of contextual arguments mapping keyword to value.
        """
        self.__context_stack = collections.deque()
        self.__context_stack.append(Context(initial_context))

    def get_new_context(self, **kwargs):
        """Create a new context with the given keyword arguments."""
        return Context(kwargs, self.__context_stack)

    @staticmethod
    def use_contextual_arguments(f):
        """Decorator which modifies a function so that it is passed arguments
        from the call or from the current context.
        """
        # Build a list of keywords to get from the context
        arg_names, _, _, defaults = inspect.getargspec(f)
        kwargs = arg_names[-len(defaults):]  # names of the keyword arguments
        default_call = dict(zip(kwargs, defaults))

        def f_(*args, **kwargs):
            self = args[0]
            # Bind all arguments with their names
            kwargs.update(dict(zip(arg_names[1:], args[1:])))

            # Update the arguments using values from the context
            cargs = {}
            for context in self.__context_stack:
                cargs.update(context.context_arguments)
            calls = {k: cargs.get(k, v) for (k, v) in iteritems(default_call)}

            # Update the arguments using values from the call
            calls = {k: kwargs.get(k, v) for (k, v) in iteritems(calls)}

            # Raise a TypeError if any `Required` sentinels remain
            for k, v in iteritems(calls):
                if v is Required:
                    raise TypeError(
                        "{!s}: missing argument {}".format(f.__name__, k))

            # Update the keyword arguments
            kwargs.update(calls)
            return f(self, **kwargs)

        f_.__doc__ = f.__doc__
        return f_


class Context(object):
    """A context object that stores arguments that may be passed to
    functions.
    """
    def __init__(self, context_arguments, stack=None):
        """Create a new context object that can be added to a stack.

        Parameters
        ----------
        context_arguments : {kwarg: value}
            A dict of contextual arguments mapping keyword to value.
        stack : :py:class:`deque`
            Context stack to which this context will append itself when
            entered.
        """
        self.context_arguments = context_arguments
        self.stack = stack

    def __enter__(self):
        # Add this context object to the stack
        self.stack.append(self)

    def __exit__(self, exception_type, exception_value, traceback):
        # Remove self from the stack
        removed = self.stack.pop()
        assert removed is self