#!/root/testventory/bin/python
import click
import json
import os

from keystoneauth1 import session
from keystoneauth1 import loading
from novaclient import client as novaclient


class ClientManager:
    """Client manager from environment variables."""

    env = {
        'auth_url': 'OS_AUTH_URL',
        'username': 'OS_USERNAME',
        'password': 'OS_PASSWORD',
        'project_name': 'OS_PROJECT_NAME',
        'user_domain_name': 'OS_USER_DOMAIN_NAME',
        'project_domain_name': 'OS_PROJECT_DOMAIN_NAME'
    }

    def __init__(self):
        """Init to None for lazy loading."""
        self.session = None
        self.nova = None

    @property
    def _interface(self):
        """Return the interface to be used as endpoint type.

        Should return internalURL or similar.

        :returns: Interface
        :rtype: str
        """
        interface = os.environ.get('OS_INTERFACE')
        return interface

    def get_session(self):
        """Get a keystone session.

        :returns: Keystone session
        :rtype: session.Session
        """
        if self.session is None:
            loader = loading.get_plugin_loader('password')
            options = {}
            for kwarg_name, varname in self.env.items():
                options[kwarg_name] = os.environ.get(varname)
            auth = loader.load_from_options(**options)
            self.session = session.Session(auth=auth)
        return self.session

    def get_nova(self):
        """Get an instance of the nova client.

        :returns: Instance of the nova client.
        :retype: novaclient.Client
        """
        if self.nova is None:
            self.nova = novaclient.Client(
                '2.1',
                session=self.get_session(),
                endpoint_type=self._interface
            )
        return self.nova


def set_meta(nova):
    """Dont use this.

    This was just to populate some existing vms with metadata for testing.
    """
    meta_map = {
        '60282d7e-c9b9-4280-96e3-1dfab7484028': {
            'stack': 'charles',
            'group': 'web'
        },
        '2b2faa9d-f0ad-4be3-9a02-e29dbef8d1e1': {
             'stack': 'charles',
             'group': 'db'
        },
        '02d9994b-c2dc-419d-9816-df15ff76c8fc': {
            'stack': 'james',
            'group': 'db'
        },
        '6b9c9a89-21e0-450d-97ce-25297db5084b': {
            'stack': 'james',
            'group': 'web'
        },
        '25afb954-2492-42a7-8d46-c64168ce564a': {
            'stack': 'james',
            'group': 'service'
        },
        'ca2cd7ff-1042-4573-b79e-0a1d4cc70ac8': {
            'stack': 'paul',
            'group': 'service'
        },
        '8dd09962-d804-466c-b011-d3a6377244bc': {
            'stack': 'paul',
            'group': 'service'
        },
        'c09c97a6-3b07-40ea-a9f5-ec405e3d28d8': {
            'stack': 'paul',
            'group': 'service'
        }
    }
    for server_id, meta_dict in meta_map.items():
        nova.servers.set_meta(server_id, meta_dict)


def iter_servers(nova, pagesize):
    """Iterate over every server.

    Could take awhile if many servers exist.

    :param nova: Instance of nova client
    :type nova: novaclient.Client
    :param pagesize: How many servers to fetch at a time from api.
    :type pagesize: int
    :yields: Server object
    :ytype: ?
    """
    keep_going = True
    marker = None
    while keep_going:
        # Get page of servers
        servers = nova.servers.list(marker=marker, limit=pagesize)

        # Stop if empty
        if not servers:
            break

        # Set marker for next page
        marker = servers[-1].id

        # Yield each server
        for server in servers:
            yield server


def ansible_host(server, host_vars):
    """Get the ansible host. This will be used to ssh into the host.

    Change this to whatever you need.
    In this example we take the first IP from the "provider-790"
    network. If not present, try the first ip.

    :param server: Server object from nova api
    :type server: ?
    :param host_vars: Dictionary of host variables so far.
    :type hosts_vars: dict:
    :returns: Single ip address
    :rtype: str
    """
    # Look for first ip on preferred network.
    preferred = 'provider-790'
    preferred = 'somethingweird'
    if preferred in host_vars.get('addresses', {}):
        addrs = host_vars['addresses'].get(preferred, [])
        if addrs:
            return addrs[0]

    # Look for first ip if not successful above
    for _, addr_list in host_vars.get('addresses', {}).items():
        if addr_list:
            return addr_list[0]

    # No ips, return None
    return None


def host_vars(server):
    """Build dict of host variables for each server.

    :param server: Server object
    :type server: ?
    :returns: Map of host variables
    :rtype: dict
    """
    thevars = {}
    thevars['server_id'] = server.id
    thevars['server_name'] = server.name
    server_dict = server.to_dict()
    thevars['addresses'] = {}
    if 'addresses' in server_dict:
        for net_name, interface_list in server_dict['addresses'].items():
            ilist = thevars['addresses'].setdefault(net_name, [])
            for interface_dict in interface_list:
                version = interface_dict.get('version')
                addr = interface_dict.get('addr')
                if addr and version == 4:
                    ilist.append(addr)
    thevars['ansible_host'] = ansible_host(server, thevars)
    return thevars


def stack_group_name(stack_value):
    """Compute name for stack.

    :returns: Name of the stack group
    :rtype: str
    """
    return 'stack_{}'.format(stack_value)


def group_group_name(group_value):
    """Compute name for an app group.

    :returns: Name of the group
    :rtype: str
    """
    return 'group_{}'.format(group_value)


def combined_group_name(stack_value, group_value):
    """Compute combined group name.

    :returns: Name of the combined group.
    :rtype: str
    """
    return 'stack_{}_{}'.format(stack_value, group_value)


@click.command()
@click.option("list_all", "--list", is_flag=True)
@click.option("--refresh", is_flag=True)
def cli(list_all, refresh):

    # Change these to reflect actual metadata keys.
    stack_key = 'stack'
    group_key = 'group'

    # Start the inventory
    inventory_dict = {
        "_meta": {
            "hostvars": {}
        }
    }
    nova = ClientManager().get_nova()

    # Iterate over every server, 100 at a time
    for server in iter_servers(nova, 100):

        # Build host vars
        inventory_dict['_meta']['hostvars'][server.id] = host_vars(server)

        stack_value = server.metadata.get(stack_key)
        group_value = server.metadata.get(group_key)

        # Create group for stack
        if stack_value is not None:
            group = inventory_dict.setdefault(
                stack_group_name(stack_value),
                {
                    'vars': {'stack': stack_value},
                    'hosts': []
                }
            )
            group['hosts'].append(server.id)

        # Create group for group
        if group_value is not None:
            group = inventory_dict.setdefault(
                group_group_name(group_value),
                {
                    'vars': {'group': group_value},
                    'hosts': []
                }
            )
            group['hosts'].append(server.id)

        # Create combined group
        if stack_value and group_value:
            group_name = combined_group_name(stack_value, group_value)
            group = inventory_dict.setdefault(
                group_name,
                {'hosts': []}
            )
            group['hosts'].append(server.id)

    inventory_json = json.dumps(inventory_dict, indent=4)
    print(inventory_json)


if __name__ == '__main__':
    cli()
