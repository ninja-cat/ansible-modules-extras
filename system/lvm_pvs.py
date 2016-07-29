#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2016, Alexander Gordeev <agordeev@mirantis.com>
# based on lvg module by Alexander Bulimov <lazywolf0@gmail.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
author: "Alexander Gordeev @(ninja-cat)"
module: lvm_pvs
short_description: Configure LVM physical volumes
description:
  - This module creates and removes physical volumes.
version_added: "2.2"
options:
  pvs:
    description:
    - List of comma-separated devices to use as physical devices.
    required: true
  pv_options:
    description:
    - Additional options to pass to C(pvcreate) when creating the physical volume.
    default: null
    required: false
    aliases:
      - pv_args
  state:
    choices: [ "present", "absent" ]
    default: present
    description:
    - Control if the physical volume exists.
    required: false
  force:
    choices: [ "yes", "no" ]
    default: "no"
    description:
    - If yes, allows to remove physical volume forcefully.
    required: false
'''

RETURN = '''
# just returns defaults
'''

EXAMPLES = '''
#Create a physical volume on /dev/sda1
- lvm_pvs: pvs=/dev/sda1

#Create a physical volume on /dev/sda1 with 2 metadata copies with metadata size 32megabytes:
- lvm_pvs: pvs=/dev/sda1 pv_options='--metadatacopies 2 --metadatasize=32m'

#Gracefully remove physical volume from /dev/sda1
- lvm_pvs: pvs=/dev/sda1 state=absent

#Forcefully remove physical volume even if it's in active use by volume group
- lvm_pvs: pvs=/dev/sda1 state=absent force=yes
'''


def find_mapper_device_name(module, dm_device):
        dmsetup_cmd = module.get_bin_path('dmsetup', True)
        mapper_prefix = '/dev/mapper/'
        rc, dm_name, err = module.run_command("%s info -C --noheadings -o name %s" % (dmsetup_cmd, dm_device))
        if rc != 0:
            module.fail_json(msg="Failed executing dmsetup command.", rc=rc, err=err)
        mapper_device = mapper_prefix + dm_name.rstrip()
        return mapper_device


def parse_pvs(module, data):
    pvs = {}
    dm_prefix = '/dev/dm-'
    for line in data.splitlines():
        parts = line.strip().split(';')
        if parts[0].startswith(dm_prefix):
            parts[0] = find_mapper_device_name(module, parts[0])
        pvs[parts[0]] = {
            'vg_name': parts[1],
            'pv_size': parts[2],
            'pv_free': parts[3],
        }
    return pvs


def main():
    module = AnsibleModule(
        argument_spec=dict(
            pvs=dict(type='list', require=True),
            pv_options=dict(default='', aliases=['pv_args']),
            state=dict(choices=["absent", "present"], default='present'),
            force=dict(type='bool', default='no'),
        ),
        supports_check_mode=True,
    )

    state = module.params['state']
    force = module.boolean(module.params['force'])
    pv_options = module.params['pv_options'].split()

    if module.params['pvs']:
        dev_list = module.params['pvs']
    elif state == 'present':
        module.fail_json(msg="No physical volumes given.")

    # LVM always uses real paths not symlinks so replace symlinks with actual path
    for idx, dev in enumerate(dev_list):
        dev_list[idx] = os.path.realpath(dev)

    if state == 'present':
        # check given devices
        for test_dev in dev_list:
            if not os.path.exists(test_dev):
                module.fail_json(msg="Device %s not found." % test_dev)

    pvs_cmd = module.get_bin_path('pvs', True)
    pvcreate_cmd = module.get_bin_path('pvcreate', True)
    pvremove_cmd = module.get_bin_path('pvremove', True)

    rc, current_pvs, err = module.run_command("%s --noheadings -o  pv_name,vg_name,pv_size,pv_free --units b --separator ';'" % pvs_cmd)
    if rc != 0:
        module.fail_json(msg="Failed executing pvs command.", rc=rc, err=err)
    pvs_data = parse_pvs(module, current_pvs)

    changed = False

    if state == 'present':
        for dev in dev_list:
            if dev not in pvs_data.keys():
                if module.check_mode:
                    module.exit_json(changed=True)
                rc, _, err = module.run_command([pvcreate_cmd] + pv_options + [dev])
                if rc == 0:
                    changed = True
                else:
                    module.fail_json(msg="Creating physical volume '%s' failed" % dev, rc=rc, err=err)
    elif state == 'absent':
        for dev in dev_list:
            if dev in pvs_data.keys():
                if module.check_mode:
                    module.exit_json(changed=True)
                if not force:
                    if pvs_data[dev]['pv_size'] == pvs_data[dev]['pv_free'] and not pvs_data[dev]['vg_name']:
                        rc, _, err = module.run_command("%s %s" % (pvremove_cmd, dev))
                        if rc == 0:
                            changed = True
                        else:
                            module.fail_json(msg="Failed to remove physical volume %s" % dev, rc=rc, err=err)
                    else:
                        module.fail_json(msg="Refuse to remove physical volume %s being in use by volume group %s without force=yes"
                                         % (dev, pvs_data[dev]['vg_name']))
                else:
                    rc, _, err = module.run_command("%s -ff -y %s" % (pvremove_cmd, dev))
                    if rc == 0:
                        changed = True
                    else:
                        module.fail_json(msg="Failed to remove physical volume %s" % dev, rc=rc, err=err)

    module.exit_json(changed=changed)

# import module snippets
from ansible.module_utils.basic import *

if __name__ == '__main__':
    main()
