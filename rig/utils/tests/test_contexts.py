"""Tests for the contextual-aware function module.
"""
import pytest
from .. import contexts


@pytest.fixture
def object_to_test():
    # Create an object with the mixin to test
    class ObjectWithContext(contexts.ContextMixin):
        def __init__(self):
            contexts.ContextMixin.__init__(self)

        @contexts.ContextMixin.use_contextual_arguments
        def method_a(self, arg0, arg1=contexts.Required, arg2=30):
            return (arg0, arg1, arg2)

        # NOTE The following method can ONLY be called in a context or with
        # named arguments, i.e., "arg1" is NEVER a positional argument.
        @contexts.ContextMixin.require_named_contextual_arguments("arg1")
        def method_b(self, arg0, *args, **kwargs):
            arg1 = kwargs.pop("arg1")
            return (arg0, arg1, args, kwargs)

    return ObjectWithContext


@pytest.mark.parametrize("arg1", [1, None, 5])
def test_contextmixin_required_passed_no_context(object_to_test, arg1):
    # Create the object
    obj = object_to_test()

    # No context
    assert obj.method_a(1, arg1) == (1, arg1, 30)
    assert obj.method_a(1, arg1, 50) == (1, arg1, 50)
    assert obj.method_a(1, arg1=arg1, arg2=50) == (1, arg1, 50)

    assert obj.method_b(1, 2, 3, arg1=0) == (1, 0, (2, 3), {})
    assert obj.method_b(0, arg1=1, bob=3) == (0, 1, tuple(), {"bob": 3})


@pytest.mark.parametrize("arg1", [1, None, 5])
def test_contextmixin_required_passed(object_to_test, arg1):
    # Create the object
    obj = object_to_test()

    # With context
    with obj.get_new_context(arg1=arg1, bob=3):
        assert obj.method_a(1) == (1, arg1, 30)
        assert obj.method_a(1, arg2=50) == (1, arg1, 50)

        # The contextual argument "bob" isn't requested by this method, so it
        # shouldn't get it.
        assert (obj.method_b("World", "Hello") ==
                ("World", arg1, ("Hello", ), {}))
        assert obj.method_b(123, arg1="Hello") == (123, "Hello", tuple(), {})


@pytest.mark.parametrize("arg1", [1, None, 5])
def test_contextmixin_required_not_passed_context(object_to_test, arg1):
    # Create the object
    obj = object_to_test()

    # No context
    with pytest.raises(TypeError) as excinfo:
        obj.method_a(1)
    assert "arg1" in str(excinfo.value)
    assert "method_a" in str(excinfo.value)

    with pytest.raises(TypeError) as excinfo:
        obj.method_a(1, arg2=50)
    assert "arg1" in str(excinfo.value)
    assert "method_a" in str(excinfo.value)

    with pytest.raises(TypeError) as excinfo:
        obj.method_b(23)
    assert "arg1" in str(excinfo.value)
    assert "method_b" in str(excinfo.value)


@pytest.mark.parametrize("arg1", [1, None, 5])
def test_contextmixin_required_not_passed(object_to_test, arg1):
    # Create the object
    obj = object_to_test()

    # With context
    with obj.get_new_context():
        with pytest.raises(TypeError) as excinfo:
            obj.method_a(1)
        assert "arg1" in str(excinfo.value)
        assert "method_a" in str(excinfo.value)

        with pytest.raises(TypeError) as excinfo:
            obj.method_a(1, arg2=50)
        assert "arg1" in str(excinfo.value)
        assert "method_a" in str(excinfo.value)

        with pytest.raises(TypeError) as excinfo:
            obj.method_b(23)
        assert "arg1" in str(excinfo.value)
        assert "method_b" in str(excinfo.value)


def test_nested(object_to_test):
    # Create the object
    obj = object_to_test()

    # With context
    with obj.get_new_context(arg1=1):
        assert obj.method_a(1) == (1, 1, 30)

        with obj.get_new_context(arg1=2):
            # Check that the stack of contexts is used
            with obj.get_new_context(arg2=3):
                assert obj.method_a(1) == (1, 2, 3)

        assert obj.method_a(1) == (1, 1, 30)