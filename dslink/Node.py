from collections import OrderedDict
import logging

from dslink.Permission import Permission
from dslink.Response import Response
from dslink.Value import Value


class Node:
    """
    Represents a Node on the Node structure.
    """

    def __init__(self, name, parent, standalone=False):
        """
        Node Constructor.
        :param name: Node name.
        :param parent: Node parent.
        :param standalone: Standalone Node structure.
        """
        self.logger = logging.getLogger("DSLink")
        if parent is not None:
            self.link = parent.link
        self.parent = parent
        self.standalone = standalone
        self.transient = False
        self.value = Value()
        self.children = {}
        self.config = OrderedDict([("$is", "node")])
        self.attributes = OrderedDict()
        self.subscribers = []
        self.streams = []
        self.removed_children = []
        # TODO(logangorence): Deprecate for v0.6
        self.set_value_callback = None
        if parent is not None:
            self.name = name
            if parent.path.endswith("/"):
                self.path = parent.path + name
            else:
                self.path = parent.path + "/" + name
        else:
            if name is not None:
                self.name = name
                self.path = "/" + name
            else:
                self.name = ""
                self.path = ""

    def get_type(self):
        """
        Get the Node's value type.
        :return: Value type.
        """
        return self.get_config("$type")

    def set_type(self, t):
        """
        Set the Node's value type.
        :param t: Type to set.
        """
        self.value.set_type(t)
        self.set_config("$type", t)

    def get_value(self):
        """
        Get the Node's value.
        :return: Node value.
        """
        if self.value.type is "enum":
            return Value.build_enum(self.value.value)
        return self.value.value

    def set_value(self, value, trigger_callback=False):
        """
        Set the Node's value.
        :param value: Value to set.
        :param trigger_callback: Set to true if you want to trigger the value set callback.
        :return: True if the value was set.
        """
        # Set value and updated timestamp
        i = self.value.set_value(value)
        if i and (not self.standalone or self.link.active):
            # Update any subscribers
            self.update_subscribers_values()
            if trigger_callback:
                if hasattr(self.set_value_callback, "__call__"):
                    self.set_value_callback(node=self, value=value)
                try:
                    self.link.profile_manager.get_profile(self.get_config("$is")).run_set_callback(SetCallbackParameters(self, value))
                except ValueError:
                    pass
        return i

    def get_config(self, key):
        """
        Get a config value.
        :param key: Key of config.
        :return: Value of config.
        """
        return self.config[key]

    def set_config(self, key, value):
        """
        Set a config value.
        :param key: Key of config.
        :param value: Value of config.
        """
        self.link.nodes_changed = True
        self.config[key] = value
        self.update_subscribers()

    def get_attribute(self, key):
        """
        Get an attribute value.
        :param key: Key of attribute.
        :return: Value of attribute.
        """
        return self.attributes[key]

    def set_attribute(self, key, value):
        """
        Set an attribute value.
        :param key: Key of attribute.
        :param value: Value of attribute.
        """
        self.link.nodes_changed = True
        self.attributes[key] = value
        self.update_subscribers()

    def set_transient(self, transient):
        """
        Set the node to be transient, which won't serialize it.
        :param transient: True if transient.
        """
        if type(transient) is not bool:
            raise TypeError("Transient must be bool")
        self.transient = transient

    def set_display_name(self, name):
        """
        Set the Node name.
        :param name: Node name.
        """
        if not isinstance(name, basestring):
            raise ValueError("Passed profile is not a string")
        self.set_config("$name", name)
        self.update_subscribers()

    def set_invokable(self, invokable):
        """
        Set invokable state.
        :param invokable: Invokable permit string or true for everyone can access.
        """
        if isinstance(invokable, basestring):
            self.set_config("$invokable", invokable)
        elif type(invokable) is bool and invokable:
            self.set_config("$invokable", "read")
        else:
            raise ValueError("Invokable is not a string or boolean")

    def set_parameters(self, parameters):
        """
        Set parameters for action.
        :param parameters: Parameters for action.
        """
        if type(parameters) is not list:
            raise ValueError("Parameters is not a list")
        self.set_config("$params", parameters)

    def set_columns(self, columns):
        """
        Set return columns for action.
        :param columns: Columns for action.
        """
        if type(columns) is not list:
            raise ValueError("Columns is not a list")
        self.set_config("$columns", columns)

    def set_profile(self, profile):
        """
        Set the Node's profile.
        :param profile: Node Profile.
        """
        if not isinstance(profile, basestring):
            raise ValueError("Passed profile is not a string")
        self.set_config("$is", profile)

    def set_writable(self, permission):
        """
        Set the writable permission.
        :param permission: Permission to set.
        """
        if isinstance(permission, basestring):
            self.set_config("$writable", permission)
        else:
            raise ValueError("Passed permission is not string")

    def stream(self):
        """
        Stream the Node.
        :return: Node stream.
        """
        out = []
        for c in self.config:
            out.append([c, self.config[c]])
        for a in self.attributes:
            out.append([a, self.attributes[a]])
        # TODO(logangorence): Investigate "RuntimeError: dictionary changed size during iteration" error.
        # TODO(logangorence): Use threading's Lock class for above issue.
        for child in self.children:
            child = self.children[child]
            if child.value.has_value():
                val = {
                    "value": child.value.value,
                    "ts": child.value.updated_at.isoformat()
                }
            else:
                val = {}
            i = dict(child.config)
            i.update(child.attributes)
            i.update(val)
            out.append([
                child.name,
                i
            ])
        for child in self.removed_children:
            out.append({
                "name": child.name,
                "change": "remove"
            })
            self.link.nodes_changed = True
        del self.removed_children[:]
        return out

    def add_child(self, child):
        """
        Add a child to this Node.
        :param child: Child to add.
        """
        if child.name in self.children:
            raise ValueError("Child already exists in %s" % self.path)
        self.children[child.name] = child
        self.link.nodes_changed = True

        if self.standalone or self.link.active:
            self.update_subscribers()

    def remove_child(self, name):
        """
        Remove a child from this Node.
        :param name: Child Node name.
        :return: True on success.
        """
        if name not in self.children:
            return False
        self.removed_children.append(self.children.pop(name))
        self.update_subscribers()
        return True

    def has_child(self, name):
        """
        Check if this Node has child of name.
        :param name: Name of child.
        :return: True if the child of name exists.
        """
        return name in self.children

    def get(self, path):
        """
        Get a Node from this position on the Node structure.
        :param path: Path of Node wanted.
        :return: Node of path.
        """
        if path == "/":
            return self
        elif path.startswith("/$"):
            return self
        elif path.startswith("/@"):
            return self
        else:
            try:
                try:
                    i = path.index("/", 2)
                    child = path[1:i]
                    return self.children[child].get(path[i:])
                except ValueError:
                    child = path[1:]
                    return self.children[child]
            except KeyError:
                import traceback
                traceback.print_exc()
                self.logger.warn("Non-existent Node requested %s on %s" % (path, self.path))

    def set_config_attr(self, path, value):
        """
        Set value/config/attribute on Node.
        :param path: Path of value to set.
        :param value: Value to set.
        """
        if path == "/" or path == self.path:
            self.set_value(value, trigger_callback=True)
        elif path.startswith("/$") or path.startswith(self.path + "/$"):
            self.set_config(path[2:], value)
        elif path.startswith("/@") or path.startswith(self.path + "/@"):
            self.set_attribute(path[2:], value)
        else:
            node = self.get(path)
            if node is not None:
                node.set_config_attr(path, value)

    def remove_config_attr(self, path):
        """
        Remove config/attribute on Node.
        :param path: Path of value to remove.
        """
        if path.startswith("/$") or path.startswith(self.path + "/$"):
            del self.config[path[2:]]
        elif path.startswith("/@") or path.startswith(self.path + "/@"):
            del self.config[path[2:]]
        else:
            self.get(path).remove_config_attr(path)

    def is_subscribed(self):
        """
        Is the Node subscribed to?
        :return: True if the Node is subscribed to.
        """
        return len(self.subscribers) is not 0

    def invoke(self, params):
        """
        Invoke the Node.
        :param params: Parameters of invoke.
        :return: Columns and values
        """
        self.logger.debug("%s invoked, with parameters: %s" % (self.path, params))
        try:
            # noinspection PyCallingNonCallable
            return (self.config["$columns"] if "$columns" in self.config else []), self.link.profile_manager.get_profile(self.get_config("$is")).run_callback(CallbackParameters(self, params))
        except ValueError:
            return [], []

    def update_subscribers(self):
        """
        Send subscription updates.
        """
        responses = []
        for stream in self.streams:
            responses.append(Response({
                "rid": stream,
                "stream": "open",
                "updates": self.stream()
            }).get_stream())
        if responses:
            self.link.wsp.sendMessage({
                "responses": responses
            })

    def update_subscribers_values(self):
        """
        Update all Subscribers of a Value change.
        """
        if self.value.has_value():
            msg = {
                "responses": []
            }
            for s in self.subscribers:
                msg["responses"].append({
                    "rid": 0,
                    "updates": [
                        [
                            s,
                            self.value.value,
                            self.value.updated_at.isoformat()
                        ]
                    ]
                })
            if len(msg["responses"]) is not 0:
                self.link.wsp.sendMessage(msg)

    def add_subscriber(self, sid):
        """
        Add a Subscriber.
        :param sid: Subscriber ID.
        """
        self.subscribers.append(sid)
        self.update_subscribers_values()

    def remove_subscriber(self, sid):
        """
        Remove a Subscriber.
        :param sid: Subscriber ID.
        """
        self.subscribers.remove(sid)

    def to_json(self):
        """
        Convert to an object that is saved to JSON.
        :return: JSON object.
        """
        out = {}

        for key in self.config:
            out[key] = self.config[key]
        for key in self.attributes:
            out[key] = self.attributes[key]
        for child in self.children:
            if not self.children[child].transient:
                out[child] = self.children[child].to_json()

        return out

    @staticmethod
    def from_json(obj, root, name, link=None):
        """
        Convert a JSON object to a String
        :param obj: Node Object.
        :param root: Root Node.
        :param name: Node Name.
        :param link: Created Node's link.
        :return: Node that was created.
        """
        node = Node(name, root)
        if link is not None:
            node.link = link

        if type(obj) is dict:
            for prop in obj:
                if prop.startswith("$"):
                    if prop == "$type":
                        node.set_type(obj[prop])
                    else:
                        node.set_config(prop, obj[prop])
                elif prop.startswith("@"):
                    node.set_attribute(prop, obj[prop])
                else:
                    node.add_child(Node.from_json(obj[prop], node, prop))

        return node


# TODO(logangorence): Rename to InvokeCallbackParameters for v0.6
class CallbackParameters:
    def __init__(self, node, params):
        self.node = node
        self.params = params


class SetCallbackParameters:
    def __init__(self, node, value):
        self.node = node
        self.value = value
