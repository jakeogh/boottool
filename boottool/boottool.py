#!/usr/bin/env python3
# -*- coding: utf8 -*-

# pylint: disable=useless-suppression             # [I0021]
# pylint: disable=missing-docstring               # [C0111] docstrings are always outdated and wrong
# pylint: disable=missing-param-doc               # [W9015]
# pylint: disable=missing-module-docstring        # [C0114]
# pylint: disable=fixme                           # [W0511] todo encouraged
# pylint: disable=line-too-long                   # [C0301]
# pylint: disable=too-many-instance-attributes    # [R0902]
# pylint: disable=too-many-lines                  # [C0302] too many lines in module
# pylint: disable=invalid-name                    # [C0103] single letter var names, name too descriptive(!)
# pylint: disable=too-many-return-statements      # [R0911]
# pylint: disable=too-many-branches               # [R0912]
# pylint: disable=too-many-statements             # [R0915]
# pylint: disable=too-many-arguments              # [R0913]
# pylint: disable=too-many-nested-blocks          # [R1702]
# pylint: disable=too-many-locals                 # [R0914]
# pylint: disable=too-many-public-methods         # [R0904]
# pylint: disable=too-few-public-methods          # [R0903]
# pylint: disable=no-member                       # [E1101] no member for base
# pylint: disable=attribute-defined-outside-init  # [W0201]
# pylint: disable=too-many-boolean-expressions    # [R0916] in if statement

from __future__ import annotations

import os
import sys
from importlib import resources
from pathlib import Path
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal

import click
import sh
from asserttool import ic
from asserttool import icp
from asserttool import root_user
from click_auto_help import AHGroup
from clicktool import click_add_options
from clicktool import click_global_options
from clicktool import tvicgvd
from compile_kernel.compile_kernel import kcompile
from devicelabeltool import write as write_device_label
from devicetool import add_partition_number_to_device
from devicetool import device_is_not_a_partition
from devicetool import get_partuuid_for_partition
from devicetool import path_is_block_special
from devicetool.cli import destroy_block_device_head_and_tail
from devicetool.cli import write_efi_partition
from devicetool.cli import write_grub_bios_partition
from eprint import eprint
from globalverbose import gvd
from mounttool import block_special_path_is_mounted
from mounttool import path_is_mounted
from pathtool import write_line_to_file
from portagetool import install_packages
from timestamptool import get_timestamp
from warntool import warn

# from devicetool import create_filesystem

signal(SIGPIPE, SIG_DFL)


def install_grub(
    boot_device: Path,
):
    if not path_is_mounted(
        Path("/boot/efi"),
    ):
        icp("/boot/efi not mounted. Exiting.")
        sys.exit(1)

    sh.env_update()
    # set +u # disable nounset        # line 22 has an unbound variable: user_id /etc/profile.d/java-config-2.sh
    # source /etc/profile || exit 1

    install_packages(
        ["grub"],
        force=False,
    )

    # if [[ "${root_filesystem}" == "zfs" ]];
    # then
    #    echo "GRUB_PRELOAD_MODULES=\"part_gpt part_msdos zfs\"" >> /etc/default/grub
    #   #echo "GRUB_CMDLINE_LINUX_DEFAULT=\"boot=zfs root=ZFS=rpool/ROOT\"" >> /etc/default/grub
    #   #echo "GRUB_CMDLINE_LINUX_DEFAULT=\"boot=zfs\"" >> /etc/default/grub
    #   #echo "GRUB_DEVICE=\"ZFS=rpool/ROOT/gentoo\"" >> /etc/default/grub
    #   # echo "GRUB_DEVICE=\"ZFS=${hostname}/ROOT/gentoo\"" >> /etc/default/grub #this was uncommented, disabled to not use hostname
    # else
    write_line_to_file(
        path=Path("/etc/default/grub"),
        line='GRUB_PRELOAD_MODULES="part_gpt part_msdos"' + "\n",
        unique=True,
    )

    from devicetool import get_root_device

    root_partition = get_root_device()
    # root_partition = Path(sh.grub_probe("--target=device", "/").strip())
    icp(root_partition)
    assert root_partition.as_posix().startswith("/dev/")
    # partition_uuid_command = sh.Command('/home/cfg/linux/hardware/disk/blkid/PARTUUID')
    # partuuid = partition_uuid_command(root_partition, _err=sys.stderr, _out=sys.stdout)
    partuuid = get_partuuid_for_partition(
        root_partition,
    )
    ic("GRUB_DEVICE partuuid:", partuuid)

    write_line_to_file(
        path=Path("/etc/default/grub"),
        line=f'GRUB_DEVICE="PARTUUID={partuuid}"' + "\n",
        unique=True,
    )

    partuuid_root_device = get_partuuid_for_partition(partition=root_partition)

    # partuuid_root_device_command = sh.Command(
    #    "/home/cfg/linux/disk/blkid/PARTUUID_root_device"
    # )
    # partuuid_root_device = partuuid_root_device_command().strip()
    icp(partuuid_root_device)

    partuuid_root_device_fstab_line = (
        "PARTUUID="
        + str(partuuid_root_device)
        + "\t/"
        + "\text4"
        + "\tnoatime"
        + "\t0"
        + "\t1"
    )
    write_line_to_file(
        path=Path("/etc/fstab"),
        line=partuuid_root_device_fstab_line + "\n",
        unique=True,
    )

    write_line_to_file(
        path=Path("/etc/default/grub"),
        # line='GRUB_CMDLINE_LINUX="net.ifnames=0 rootflags=noatime intel_iommu=off"'
        line='GRUB_CMDLINE_LINUX="net.ifnames=0 rootflags=noatime earlyprintk=vga"'
        + "\n",
        unique=True,
    )

    sh.ln("-sf", "/proc/self/mounts", "/etc/mtab")

    sh.grub_install(
        "--compress=no",
        "--target=x86_64-efi",
        "--efi-directory=/boot/efi",
        "--boot-directory=/boot",
        "--removable",
        "--recheck",
        "--no-rs-codes",
        "--debug-image=linux",
        "--debug",
        boot_device,
        _out=sys.stdout,
        _err=sys.stderr,
    )
    sh.grub_install(
        "--compress=no",
        "--target=i386-pc",
        "--boot-directory=/boot",
        "--recheck",
        "--no-rs-codes",
        "--force",  # otherwise it complains about blocklists
        boot_device,
        _out=sys.stdout,
        _err=sys.stderr,
    )

    sh.grub_mkconfig("-o", "/boot/grub/grub.cfg", _out=sys.stdout, _err=sys.stderr)

    with open(Path("/install_status"), "a", encoding="utf8") as fh:
        fh.write(get_timestamp() + sys.argv[0] + "complete" + "\n")


def create_boot_device(
    ctx,
    *,
    device: Path,
    partition_table: str,
    filesystem: str,
    force: bool,
    verbose: bool = False,
):
    assert device_is_not_a_partition(
        device=device,
        verbose=verbose,
    )
    assert isinstance(device, Path)

    eprint(
        "installing gpt/grub_bios/efi on boot device:",
        device,
        "(" + partition_table + ")",
        "(" + filesystem + ")",
    )
    assert path_is_block_special(device)
    assert not block_special_path_is_mounted(
        device,
        verbose=verbose,
    )

    if not force:
        warn(
            (device,),
            verbose=verbose,
        )

    # dont do this here, want to be able to let zfs make
    # the gpt and it's partitions before making bios_grub and EFI
    # destroy_block_device_head_and_tail(device=device, force=True)

    if partition_table == "gpt":
        #    if filesystem != 'zfs':
        ctx.invoke(
            destroy_block_device_head_and_tail,
            device=device,
            force=force,
            no_backup=False,
            verbose=True,
        )

        ctx.invoke(
            write_device_label,
            device=device,
            label="gpt",
            force=force,
            verbose=verbose,
        )  # zfs does this

    # if filesystem == 'zfs':
    #    assert False
    #    ## 2 if zfs made sda1 and sda9
    #    #ctx.invoke(write_grub_bios_partition,
    #    #           device=device,
    #    #           force=True,
    #    #           start='48s',
    #    #           end='1023s',
    #    #           partition_number='2',
    #    #           verbose=verbose,
    #    #           )
    # else:
    ctx.invoke(
        write_grub_bios_partition,
        device=device,
        force=True,
        start="48s",
        end="1023s",
        partition_number=1,
        verbose=verbose,
    )

    # if filesystem != 'zfs':
    ctx.invoke(
        write_efi_partition,
        device=device,
        force=True,
        start="1024s",
        end="18047s",
        partition_number=2,
        verbose=verbose,
    )  # this is /dev/sda9 on zfs
    # 100M = (205824-1024)*512
    # ctx.invoke(write_efi_partition,
    #           device=device,
    #           force=True,
    #           start='1024s',
    #           end='205824s',
    #           partition_number='2',
    #           verbose=verbose,
    #           ) # this is /dev/sda9 on zfs

    # if filesystem == 'zfs':
    #    assert False
    #    #create_filesystem(device=device + '9',
    #    #                  filesystem='fat16',
    #    #                  force=True,
    #    #                  raw_device=False,
    #    #                  verbose=verbose,
    #    #                  )


@click.group(no_args_is_help=True, cls=AHGroup)
@click_add_options(click_global_options)
@click.pass_context
def cli(
    ctx,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
):
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )


@cli.command()
@click.argument(
    "device",
    type=click.Path(
        exists=True,
        dir_okay=False,
        file_okay=True,
        allow_dash=False,
        path_type=Path,
    ),
    nargs=1,
    required=True,
)
@click.option("--force", is_flag=True, required=False)
@click_add_options(click_global_options)
@click.pass_context
def write_boot_partition(
    *,
    device: Path,
    force: bool,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
):
    ic("creating boot partition (for grub config, stage2, vmlinuz) on:", device)
    assert device_is_not_a_partition(
        device=device,
        verbose=verbose,
    )
    assert path_is_block_special(device)
    assert not block_special_path_is_mounted(
        device,
        verbose=verbose,
    )

    if not force:
        warn(
            (device,),
            verbose=verbose,
        )

    partition_number = 3
    partition = add_partition_number_to_device(
        device=device, partition_number=partition_number, verbose=verbose
    )
    start = "100MiB"
    end = "400MiB"

    sh.parted(
        "-a",
        "optimal",
        str(device),
        "--script -- mkpart primary " + str(start) + " " + str(end),
        _out=sys.stdout,
        _err=sys.stderr,
    )
    sh.parted(
        device, "--script -- name " + str(partition_number) + " bootfs", verbose=True
    )
    mkfs_command = sh.Command("mkfs.ext4")
    mkfs_command(partition, _out=sys.stdout, _err=sys.stderr)


@cli.command()
@click.argument("boot_device", type=click.Path(path_type=Path))
@click_add_options(click_global_options)
@click.pass_context
def make_hybrid_mbr(
    ctx,
    *,
    boot_device: Path,
    verbose: bool = False,
    verbose_inf: bool,
    dict_output: bool,
):
    if not root_user():
        ic("You must be root.")
        sys.exit(1)

    assert path_is_block_special(boot_device)

    with resources.path(
        "boottool", "gpart_make_hybrid_mbr.sh"
    ) as _hybrid_mbr_script_path:
        icp(_hybrid_mbr_script_path)

        make_hybrid_mbr_command = sh.Command(_hybrid_mbr_script_path)
        make_hybrid_mbr_command(
            _hybrid_mbr_script_path.parent / Path("gpart_make_hybrid_mbr.exp"),
            boot_device,
            _out=sys.stdout,
            _err=sys.stderr,
        )


@cli.command()
@click.option("--boot-device", is_flag=False, required=True)
@click.option(
    "--boot-device-partition-table",
    is_flag=False,
    required=False,
    type=click.Choice(["gpt"]),
    default="gpt",
)
@click.option(
    "--boot-filesystem",
    is_flag=False,
    required=False,
    type=click.Choice(["ext4"]),
    default="ext4",
)
@click.option("--force", is_flag=True, required=False)
@click.option("--compile-kernel", "_compile_kernel", is_flag=True, required=False)
@click.option("--configure-kernel", is_flag=True, required=False)
@click_add_options(click_global_options)
@click.pass_context
def create_boot_device_for_existing_root(
    ctx,
    boot_device,
    boot_device_partition_table,
    boot_filesystem,
    _compile_kernel: bool,
    configure_kernel: bool,
    force: bool,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
):
    if configure_kernel:
        _compile_kernel = True

    assert False  ## needs to ctx.invoke(install_brub)
    if not root_user():
        ic("You must be root.")
        sys.exit(1)

    mount_path_boot = Path("/boot")
    ic(mount_path_boot)
    assert not path_is_mounted(
        mount_path_boot,
        verbose=verbose,
    )

    mount_path_boot_efi = mount_path_boot / Path("efi")
    ic(mount_path_boot_efi)
    assert not path_is_mounted(
        mount_path_boot_efi,
        verbose=verbose,
    )

    assert device_is_not_a_partition(
        device=boot_device,
        verbose=verbose,
    )

    ic(
        "installing grub on boot device:",
        boot_device,
        boot_device_partition_table,
        boot_filesystem,
    )
    assert path_is_block_special(boot_device)
    assert not block_special_path_is_mounted(
        boot_device,
        verbose=verbose,
    )
    if not force:
        warn(
            (boot_device,),
            verbose=verbose,
        )
    create_boot_device(
        ctx,
        device=boot_device,
        partition_table=boot_device_partition_table,
        filesystem=boot_filesystem,
        force=True,
        verbose=verbose,
    )
    ctx.invoke(
        write_boot_partition,
        device=boot_device,
        force=True,
        verbose=verbose,
    )

    hybrid_mbr_command = sh.Command("gpart_make_hybrid_mbr.sh")
    hybrid_mbr_command(boot_device, _out=sys.stdout, _err=sys.stderr)

    os.makedirs(mount_path_boot, exist_ok=True)
    boot_partition_path = add_partition_number_to_device(
        device=boot_device,
        partition_number=3,
        verbose=verbose,
    )
    assert not path_is_mounted(
        mount_path_boot,
        verbose=verbose,
    )
    sh.mount(
        boot_partition_path, str(mount_path_boot), _out=sys.stdout, _err=sys.stderr
    )
    assert path_is_mounted(
        mount_path_boot,
        verbose=verbose,
    )

    os.makedirs(mount_path_boot_efi, exist_ok=True)

    efi_partition_path = add_partition_number_to_device(
        device=boot_device,
        partition_number=2,
        verbose=verbose,
    )
    assert not path_is_mounted(
        mount_path_boot_efi,
        verbose=verbose,
    )
    sh.mount(
        efi_partition_path, str(mount_path_boot_efi), _out=sys.stdout, _err=sys.stderr
    )
    assert path_is_mounted(
        mount_path_boot_efi,
        verbose=verbose,
    )

    install_grub_command = sh.Command("post_chroot_install_grub.sh")
    install_grub_command(boot_device, _out=sys.stdout, _err=sys.stderr)

    if _compile_kernel:
        kcompile(
            fix=True,
            warn_only=False,
            symlink_config=False,
            configure=configure_kernel,
            configure_only=False,
            force=force,
            no_check_boot=True,
            verbose=verbose,
        )

    sh.grub_mkconfig("-o", "/boot/grub/grub.cfg", _out=sys.stdout, _err=sys.stderr)


@cli.command("install-grub")
@click.argument(
    "boot_device",
    type=click.Path(
        exists=True,
        dir_okay=False,
        file_okay=True,
        allow_dash=False,
        path_type=Path,
    ),
    nargs=1,
    required=True,
)
@click_add_options(click_global_options)
@click.pass_context
def _install_grub(
    ctx,
    *,
    boot_device: Path,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
):
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    install_grub(boot_device=boot_device)
