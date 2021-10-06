#!/usr/bin/env python3
# -*- coding: utf8 -*-

# flake8: noqa           # flake8 has no per file settings :(
# pylint: disable=C0111  # docstrings are always outdated and wrong
# pylint: disable=C0114  #      Missing module docstring (missing-module-docstring)
# pylint: disable=W0511  # todo is encouraged
# pylint: disable=C0301  # line too long
# pylint: disable=R0902  # too many instance attributes
# pylint: disable=C0302  # too many lines in module
# pylint: disable=C0103  # single letter var names, func name too descriptive
# pylint: disable=R0911  # too many return statements
# pylint: disable=R0912  # too many branches
# pylint: disable=R0915  # too many statements
# pylint: disable=R0913  # too many arguments
# pylint: disable=R1702  # too many nested blocks
# pylint: disable=R0914  # too many local variables
# pylint: disable=R0903  # too few public methods
# pylint: disable=E1101  # no member for base
# pylint: disable=W0201  # attribute defined outside __init__
# pylint: disable=R0916  # Too many boolean expressions in if statement
# pylint: disable=C0305  # Trailing newlines editor should fix automatically, pointless warning
# pylint: disable=C0413  # TEMP isort issue [wrong-import-position] Import "from pathlib import Path" should be placed at the top of the module [C0413]

import os
import sys
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal

import click
import sh

signal(SIGPIPE, SIG_DFL)
from pathlib import Path
from typing import ByteString
from typing import Generator
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union

from asserttool import eprint
from asserttool import ic
from asserttool import nevd
from asserttool import root_user
from blocktool import add_partition_number_to_device
from blocktool import create_filesystem
from blocktool import destroy_block_device_head_and_tail
from blocktool import device_is_not_a_partition
from blocktool import path_is_block_special
from blocktool import warn
from compile_kernel.compile_kernel import kcompile
from devicetool import get_partuuid_for_partition
from devicetool import write_efi_partition
from devicetool import write_gpt
from devicetool import write_grub_bios_partition
from mounttool import block_special_path_is_mounted
from mounttool import path_is_mounted
from pathtool import write_line_to_file
from portagetool import install_package
from timetool import get_timestamp


def create_boot_device(ctx, *,
                       device,
                       partition_table,
                       filesystem,
                       force: bool,
                       verbose: bool,
                       debug: bool,):

    assert device_is_not_a_partition(device=device, verbose=verbose, debug=debug,)

    eprint("installing gpt/grub_bios/efi on boot device:",
           device,
           '(' + partition_table + ')',
           '(' + filesystem + ')',)
    assert path_is_block_special(device)
    assert not block_special_path_is_mounted(device, verbose=verbose, debug=debug,)

    if not force:
        warn((device,), verbose=verbose, debug=debug,)

    # dont do this here, want to be able to let zfs make
    # the gpt and it's partitions before making bios_grub and EFI
    #destroy_block_device_head_and_tail(device=device, force=True)

    if partition_table == 'gpt':
        if filesystem != 'zfs':
            ctx.invoke(destroy_block_device_head_and_tail,
                       device=device,
                       force=force,
                       no_backup=False,
                       verbose=True,
                       debug=debug,)

            ctx.invoke(write_gpt,
                       device=device,
                       no_wipe=True,
                       force=force,
                       no_backup=False,
                       verbose=verbose,
                       debug=debug,) # zfs does this

    if filesystem == 'zfs':
        # 2 if zfs made sda1 and sda9
        ctx.invoke(write_grub_bios_partition,
                   device=device,
                   force=True,
                   start='48s',
                   end='1023s',
                   partition_number='2',
                   verbose=verbose,
                   debug=debug,)
    else:
        ctx.invoke(write_grub_bios_partition,
                   device=device,
                   force=True,
                   start='48s',
                   end='1023s',
                   partition_number='1',
                   verbose=verbose,
                   debug=debug,)

    if filesystem != 'zfs':
        ctx.invoke(write_efi_partition,
                   device=device,
                   force=True,
                   start='1024s',
                   end='18047s',
                   partition_number='2',
                   verbose=verbose,
                   debug=debug,) # this is /dev/sda9 on zfs
        # 100M = (205824-1024)*512
        #ctx.invoke(write_efi_partition,
        #           device=device,
        #           force=True,
        #           start='1024s',
        #           end='205824s',
        #           partition_number='2',
        #           verbose=verbose,
        #           debug=debug,) # this is /dev/sda9 on zfs

    if filesystem == 'zfs':
        assert False
        create_filesystem(device=device + '9',
                          filesystem='fat16',
                          force=True,
                          raw_device=False,
                          verbose=verbose,
                          debug=debug,)

@click.group()
@click.option('--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
@click.pass_context
def cli(ctx,
        verbose: bool,
        debug: bool,
        ):

    null, end, verbose, debug = nevd(ctx=ctx,
                                     printn=False,
                                     ipython=False,
                                     verbose=verbose,
                                     debug=debug,)


@cli.command()
@click.option('--device', is_flag=False, required=True)
@click.option('--force', is_flag=True, required=False)
@click.option('--verbose', is_flag=True, required=False)
@click.option('--debug', is_flag=True, required=False)
def write_boot_partition(*,
                         device: str,
                         force: bool,
                         verbose: bool,
                         debug: bool,
                         ):
    ic('creating boot partition  (for grub config, stage2, vmlinuz) on:', device)
    assert device_is_not_a_partition(device=device, verbose=verbose, debug=debug,)
    assert path_is_block_special(device)
    assert not block_special_path_is_mounted(device, verbose=verbose, debug=debug,)

    if not force:
        warn((device,), verbose=verbose, debug=debug,)

    partition_number = '3'
    partition = add_partition_number_to_device(device=device,
                                               partition_number=partition_number,
                                               verbose=verbose)
    start = "100MiB"
    end = "400MiB"

    sh.parted('-a', 'optimal', str(device), '--script -- mkpart primary ' + str(start) + ' ' + str(end), _out=sys.stdout, _err=sys.stderr)
    sh.parted(device, '--script -- name ' + str(partition_number) + " bootfs", verbose=True)
    mkfs_command = sh.Command('mkfs.ext4')
    mkfs_command(partition, _out=sys.stdout, _err=sys.stderr)


@cli.command()
@click.argument("boot_device")
@click.option('--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
def make_hybrid_mbr(*,
                    boot_device: str,
                    verbose: bool,
                    debug: bool,
                    ):

    if not root_user():
        ic('You must be root.')
        sys.exit(1)

    assert path_is_block_special(boot_device)

    make_hybrid_mbr_command = sh.Command('/home/cfg/_myapps/sendgentoo/sendgentoo/gpart_make_hybrid_mbr.sh')
    make_hybrid_mbr_command(boot_device, _out=sys.stdout, _err=sys.stderr)


@cli.command()
@click.option('--boot-device',                 is_flag=False, required=True)
@click.option('--boot-device-partition-table', is_flag=False, required=False, type=click.Choice(['gpt']), default="gpt")
@click.option('--boot-filesystem',             is_flag=False, required=False, type=click.Choice(['ext4']), default="ext4")
@click.option('--force',                       is_flag=True,  required=False)
@click.option('--compile-kernel', "_compile_kernel", is_flag=True, required=False)
@click.option('--configure-kernel',            is_flag=True,  required=False)
@click.option('--verbose',                     is_flag=True,  required=False)
@click.option('--debug',                       is_flag=True,  required=False)
@click.pass_context
def create_boot_device_for_existing_root(ctx,
                                         boot_device,
                                         boot_device_partition_table,
                                         boot_filesystem,
                                         _compile_kernel: bool,
                                         configure_kernel: bool,
                                         force: bool,
                                         verbose: bool,
                                         debug: bool,):
    if configure_kernel:
        _compile_kernel = True

    if not root_user():
        ic('You must be root.')
        sys.exit(1)

    mount_path_boot = Path('/boot')
    ic(mount_path_boot)
    assert not path_is_mounted(mount_path_boot, verbose=verbose, debug=debug,)

    mount_path_boot_efi = mount_path_boot / Path('efi')
    ic(mount_path_boot_efi)
    assert not path_is_mounted(mount_path_boot_efi, verbose=verbose, debug=debug,)

    assert device_is_not_a_partition(device=boot_device, verbose=verbose, debug=debug,)

    ic('installing grub on boot device:',
       boot_device,
       boot_device_partition_table,
       boot_filesystem)
    assert path_is_block_special(boot_device)
    assert not block_special_path_is_mounted(boot_device, verbose=verbose, debug=debug,)
    if not force:
        warn((boot_device,), verbose=verbose, debug=debug,)
    create_boot_device(ctx,
                       device=boot_device,
                       partition_table=boot_device_partition_table,
                       filesystem=boot_filesystem,
                       force=True,
                       verbose=verbose,
                       debug=debug,)
    ctx.invoke(write_boot_partition,
               device=boot_device,
               force=True,
               verbose=verbose,
               debug=debug,)

    hybrid_mbr_command = sh.Command("/home/cfg/_myapps/sendgentoo/sendgentoo/gpart_make_hybrid_mbr.sh")
    hybrid_mbr_command(boot_device, _out=sys.stdout, _err=sys.stderr)

    os.makedirs(mount_path_boot, exist_ok=True)
    boot_partition_path = add_partition_number_to_device(device=boot_device, partition_number="3")
    assert not path_is_mounted(mount_path_boot, verbose=verbose, debug=debug,)
    sh.mount(boot_partition_path, str(mount_path_boot), _out=sys.stdout, _err=sys.stderr)
    assert path_is_mounted(mount_path_boot, verbose=verbose, debug=debug,)

    os.makedirs(mount_path_boot_efi, exist_ok=True)

    efi_partition_path = add_partition_number_to_device(device=boot_device, partition_number="2")
    assert not path_is_mounted(mount_path_boot_efi, verbose=verbose, debug=debug,)
    sh.mount(efi_partition_path, str(mount_path_boot_efi), _out=sys.stdout, _err=sys.stderr)
    assert path_is_mounted(mount_path_boot_efi, verbose=verbose, debug=debug,)

    install_grub_command = sh.Command("/home/cfg/_myapps/sendgentoo/sendgentoo/post_chroot_install_grub.sh")
    install_grub_command(boot_device, _out=sys.stdout, _err=sys.stderr)

    if _compile_kernel:
        kcompile(configure=configure_kernel,
                 force=force,
                 no_check_boot=True,
                 verbose=verbose,
                 debug=debug)

    sh.grub_mkconfig('-o', '/boot/grub/grub.cfg', _out=sys.stdout, _err=sys.stderr)


@cli.command()
@click.argument("boot_device",
                type=click.Path(exists=True,
                                dir_okay=False,
                                file_okay=True,
                                allow_dash=False,
                                path_type=Path,),
                nargs=1,
                required=True,)
@click.option('--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
@click.pass_context
def install_grub(ctx,
                 boot_device: Path,
                 verbose: bool,
                 debug: bool,
                 ):

    null, end, verbose, debug = nevd(ctx=ctx,
                                     printn=False,
                                     ipython=False,
                                     verbose=verbose,
                                     debug=debug,)

    if not path_is_mounted(Path("/boot/efi"), verbose=verbose, debug=debug,):
        ic("/boot/efi not mounted. Exiting.")
        sys.exit(1)

    sh.env_update()
    #set +u # disable nounset        # line 22 has an unbound variable: user_id /etc/profile.d/java-config-2.sh
    #source /etc/profile || exit 1
    #set -o nounset

    install_package('grub')

    #if [[ "${root_filesystem}" == "zfs" ]];
    #then
    #    echo "GRUB_PRELOAD_MODULES=\"part_gpt part_msdos zfs\"" >> /etc/default/grub
    #   #echo "GRUB_CMDLINE_LINUX_DEFAULT=\"boot=zfs root=ZFS=rpool/ROOT\"" >> /etc/default/grub
    #   #echo "GRUB_CMDLINE_LINUX_DEFAULT=\"boot=zfs\"" >> /etc/default/grub
    #   #echo "GRUB_DEVICE=\"ZFS=rpool/ROOT/gentoo\"" >> /etc/default/grub
    #   # echo "GRUB_DEVICE=\"ZFS=${hostname}/ROOT/gentoo\"" >> /etc/default/grub #this was uncommented, disabled to not use hostname
    #else
    write_line_to_file(path=Path('/etc/default/grub'),
                       line='GRUB_PRELOAD_MODULES="part_gpt part_msdos"' + '\n',
                       unique=True,
                       verbose=verbose,
                       debug=debug,)

    root_partition = sh.grub_probe('--target=device', '/')
    ic(root_partition)
    assert root_partition.startswith('/dev/')
    ic(root_partition)
    #partition_uuid_command = sh.Command('/home/cfg/linux/hardware/disk/blkid/PARTUUID')
    #partuuid = partition_uuid_command(root_partition, _err=sys.stderr, _out=sys.stdout)
    partuuid = get_partuuid_for_partition(root_partition, verbose=verbose, debug=debug)
    ic('GRUB_DEVICE partuuid:', partuuid)

    write_line_to_file(path=Path('/etc/default/grub'),
                       line='GRUB_DEVICE="PARTUUID={partuuid}"'.format(partuuid=partuuid) + '\n',
                       unique=True,
                       verbose=verbose,
                       debug=debug,)
    partuuid_root_device_command = sh.Command('/home/cfg/linux/disk/blkid/PARTUUID_root_device')
    partuuid_root_device = partuuid_root_device_command()


    partuuid_root_device_fstab_line = 'PARTUUID=' + partuuid_root_device + '\t/' + '\text4' + '\tnoatime' + '\t0'+ '\t1'
    write_line_to_file(path=Path('/etc/fstab'),
                       line=partuuid_root_device_fstab_line + '\n',
                       unique=True,
                       verbose=verbose,
                       debug=debug,)

    #grep -E "^GRUB_CMDLINE_LINUX=\"net.ifnames=0 rootflags=noatime irqpoll\"" /etc/default/grub || { echo "GRUB_CMDLINE_LINUX=\"net.ifnames=0 rootflags=noatime irqpoll\"" >> /etc/default/grub ; }
    write_line_to_file(path=Path('/etc/default/grub'),
                       line='GRUB_CMDLINE_LINUX="net.ifnames=0 rootflags=noatime intel_iommu=off"' + '\n',
                       unique=True,
                       verbose=verbose,
                       debug=debug,)

    sh.ln('-sf', '/proc/self/mounts', '/etc/mtab')

    sh.grub_install('--compress=no', '--target=x86_64-efi', '--efi-directory=/boot/efi', '--boot-directory=/boot', '--removable', '--recheck', '--no-rs-codes', boot_device, _out=sys.stdout, _err=sys.stderr)
    sh.grub_install('--compress=no', '--target=i386-pc', '--boot-directory=/boot', '--recheck', '--no-rs-codes', boot_device, _out=sys.stdout, _err=sys.stderr)

    sh.grub_mkconfig('-o', '/boot/grub/grub.cfg', _out=sys.stdout, _err=sys.stderr)

    with open('/install_status', 'a') as fh:
        fh.write(get_timestamp() + sys.argv[0] + 'complete'  + '\n')


if __name__ == '__main__':
    # pylint: disable=E1120
    cli()

