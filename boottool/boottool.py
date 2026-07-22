#!/usr/bin/env python3

import os
import sys
from importlib import resources
from pathlib import Path
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal

import click
import hs
from asserttool import am_root
from asserttool import ic
from asserttool import icp
from click_auto_help import AHGroup
from clicktool import click_add_options
from clicktool import click_global_options
from clicktool import tvicgvd
from compile_kernel.compile_kernel import compile_and_install_kernel
from compile_kernel.compile_kernel import install_compiled_kernel
from devicelabeltool import write as write_device_label
from devicetool import add_partition_number_to_device
from devicetool import device_is_not_a_partition
from devicetool import get_partuuid_for_partition
from devicetool import get_root_device
from devicetool import path_is_block_special
from devicetool.cli import destroy_block_device_head_and_tail
from devicetool.cli import write_efi_partition
from devicetool.cli import write_grub_bios_partition
from eprint import eprint
from filetool import ensure_line_in_config_file
from globalverbose import gvd
from mounttool import block_special_path_is_mounted
from mounttool import path_is_mounted
from portagetool import install_packages
from timestamptool import get_timestamp
from warntool import warn

signal(SIGPIPE, SIG_DFL)


def generate_grub_config(path: Path, replace: bool) -> None:
    if not replace:
        if path.exists():
            raise FileExistsError(path)

    hs.Command("grub-mkconfig")(
        "-o",
        path.as_posix(),
        _out=sys.stdout,
        _err=sys.stderr,
    )


def install_grub(
    boot_device: Path,
    skip_uefi: bool,
    debug_grub: bool,
) -> None:
    if not skip_uefi:
        if not path_is_mounted(Path("/boot/efi")):
            eprint("/boot/efi not mounted. Exiting.")
            sys.exit(1)

    hs.Command("env-update")()

    install_packages(
        ["grub"],
        force=False,
        upgrade_only=True,
    )

    ensure_line_in_config_file(
        path=Path("/etc/default/grub"),
        line='GRUB_PRELOAD_MODULES="part_gpt part_msdos"',
        ignore_leading_whitespace=True,
        comment_marker="#",
    )

    root_partition = get_root_device()
    icp(root_partition)
    assert root_partition.as_posix().startswith("/dev/")
    partuuid = get_partuuid_for_partition(root_partition)
    ic("GRUB_DEVICE partuuid:", partuuid)

    ensure_line_in_config_file(
        path=Path("/etc/default/grub"),
        line=f'GRUB_DEVICE="PARTUUID={partuuid}"',
        ignore_leading_whitespace=True,
        comment_marker="#",
    )

    ensure_line_in_config_file(
        path=Path("/etc/fstab"),
        line=f"PARTUUID={partuuid}\t/\text4\tnoatime\t0\t1",
        ignore_leading_whitespace=True,
        comment_marker="#",
    )

    ensure_line_in_config_file(
        path=Path("/etc/default/grub"),
        line='GRUB_CMDLINE_LINUX="net.ifnames=0 rootflags=noatime earlyprintk=vga"',
        ignore_leading_whitespace=True,
        comment_marker="#",
    )

    hs.Command("ln")("-sf", "/proc/self/mounts", "/etc/mtab")

    if not skip_uefi:
        grub_install = hs.Command("grub-install")
        grub_install.bake(
            "--compress=no",
            "--core-compress=none",
            "--target=x86_64-efi",
            "--efi-directory=/boot/efi",
            "--boot-directory=/boot",
            "--removable",
            "--recheck",
            "--no-rs-codes",
            "--debug-image=linux",
            "--debug",
        )
        grub_install(
            boot_device.as_posix(),
            _out=sys.stdout,
            _err=sys.stderr,
        )

    grub_install = hs.Command("grub-install")
    grub_install.bake(
        "--compress=no",
        "--core-compress=none",
        "--target=i386-pc",
        "--boot-directory=/boot",
        "--recheck",
        "--no-rs-codes",
        "--debug",
        "--force",  # otherwise it complains about blocklists... sometimes
    )
    if debug_grub:
        # --debug-image=all basically never boots because it's so slow
        # disabled here: relocator,scripting,lexer
        grub_install.bake(
            "--debug-image=acpi,affs,ahci,appleload,arcdisk,archelp,ata,atkeyb,biosdisk,bsd,btrfs,cache,cbfs,chain,crypt,cryptodisk,datetime,devalias,disk,diskfilter,dl,dns,drivemap,efi,efidisk,efiemu,ehci,elf,exfat,expand,fat,fb,fdt,fixvideo,font,fs,geli,gpt,hostdisk,init,jpeg,keystatus,linux,loader,luks,memdisk,mm,mmap,modules,multiboot_loader,nativedisk,net,ohci,partition,pata,play,reiserfs_tree,scsi,serial,smbios,syslinux,tftp,tga,ubootdisk,uhci,usb,usb_keyboard,usbms,video,xen,xen_loader,xfs,xnu,zfs"
        )

    grub_install(
        boot_device.as_posix(),
        _out=sys.stdout,
        _err=sys.stderr,
    )

    generate_grub_config(path=Path("/boot/grub/grub.cfg"), replace=True)

    with open(Path("/install_status"), "a", encoding="utf8") as fh:
        fh.write(f"{get_timestamp()} {sys.argv[0]} complete\n")


def create_boot_device(
    ctx: click.Context,
    *,
    device: Path,
    partition_table: str,
    filesystem: str,
    force: bool,
    verbose: bool = False,
) -> None:
    assert isinstance(device, Path)
    assert device_is_not_a_partition(device=device)

    eprint(
        "installing gpt/grub_bios/efi on boot device:",
        device,
        f"({partition_table}) ({filesystem})",
    )
    assert path_is_block_special(device, symlink_ok=True)
    assert not block_special_path_is_mounted(device)

    if not force:
        warn((device,), symlink_ok=True)

    if partition_table == "gpt":
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
        )

    ctx.invoke(
        write_grub_bios_partition,
        device=device,
        force=True,
        start="48s",
        end="2047s",
        partition_number=1,
        verbose=verbose,
    )

    ctx.invoke(
        write_efi_partition,
        device=device,
        force=True,
        start="2048s",
        end="18047s",
        partition_number=2,
        verbose=verbose,
    )


@click.group(no_args_is_help=True, cls=AHGroup)
@click_add_options(click_global_options)
@click.pass_context
def cli(
    ctx: click.Context,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
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
    ctx: click.Context,
    *,
    device: Path,
    force: bool,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )
    ic("creating boot partition (for grub config, stage2, vmlinuz) on:", device)
    assert device_is_not_a_partition(device=device)
    assert path_is_block_special(device, symlink_ok=True)
    assert not block_special_path_is_mounted(device)

    if not force:
        warn(
            (device,),
            symlink_ok=True,
        )

    partition_number = 3
    partition = add_partition_number_to_device(
        device=device,
        partition_number=partition_number,
    )

    hs.Command("parted")(
        "-a",
        "optimal",
        device.as_posix(),
        "--script",
        "--",
        "mkpart",
        "primary",
        "100MiB",
        "400MiB",
    )
    hs.Command("parted")(
        device.as_posix(),
        "--script",
        "--",
        "name",
        str(partition_number),
        "bootfs",
    )
    hs.Command("mkfs.ext4")(partition.as_posix(), _out=sys.stdout, _err=sys.stderr)


@cli.command()
@click.argument(
    "boot_device",
    type=click.Path(
        exists=True,
        dir_okay=False,
        file_okay=True,
        allow_dash=False,
        path_type=Path,
    ),
)
@click_add_options(click_global_options)
@click.pass_context
def make_hybrid_mbr(
    ctx: click.Context,
    *,
    boot_device: Path,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )
    am_root()

    assert path_is_block_special(boot_device, symlink_ok=True)

    with resources.as_file(resources.files("boottool")) as _pkg_dir:
        script_path = _pkg_dir / "gpart_make_hybrid_mbr.sh"
        exp_path = _pkg_dir / "gpart_make_hybrid_mbr.exp"
        icp(script_path)
        hs.Command(script_path.as_posix())(
            exp_path.as_posix(),
            boot_device.as_posix(),
            _out=sys.stdout,
            _err=sys.stderr,
        )


@cli.command()
@click.option(
    "--boot-device",
    type=click.Path(
        exists=True,
        dir_okay=False,
        file_okay=True,
        allow_dash=False,
        path_type=Path,
    ),
    required=True,
)
@click.option(
    "--boot-device-partition-table",
    is_flag=False,
    type=click.Choice(["gpt"]),
    default="gpt",
)
@click.option(
    "--boot-filesystem",
    is_flag=False,
    type=click.Choice(["ext4"]),
    default="ext4",
)
@click.option("--force", is_flag=True)
@click.option("--skip-uefi", is_flag=True)
@click.option("--debug-grub", is_flag=True)
@click.option("--compile-kernel", "_compile_kernel", is_flag=True)
@click.option("--configure-kernel", is_flag=True)
@click_add_options(click_global_options)
@click.pass_context
def create_boot_device_for_existing_root(
    ctx: click.Context,
    boot_device: Path,
    boot_device_partition_table: str,
    boot_filesystem: str,
    _compile_kernel: bool,
    configure_kernel: bool,
    force: bool,
    debug_grub: bool,
    verbose_inf: bool,
    dict_output: bool,
    skip_uefi: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )
    if configure_kernel:
        _compile_kernel = True

    am_root()

    mount_path_boot = Path("/boot")
    ic(mount_path_boot)
    assert not path_is_mounted(mount_path_boot)

    mount_path_boot_efi = mount_path_boot / "efi"
    ic(mount_path_boot_efi)
    assert not path_is_mounted(mount_path_boot_efi)

    assert device_is_not_a_partition(device=boot_device)

    ic(
        "installing grub on boot device:",
        boot_device,
        boot_device_partition_table,
        boot_filesystem,
    )
    assert path_is_block_special(boot_device, symlink_ok=True)
    assert not block_special_path_is_mounted(boot_device)
    if not force:
        warn(
            (boot_device,),
            symlink_ok=True,
        )
    create_boot_device(
        ctx,
        device=boot_device,
        partition_table=boot_device_partition_table,
        filesystem=boot_filesystem,
        force=True,
    )
    ctx.invoke(
        write_boot_partition,
        device=boot_device,
        force=True,
        verbose=verbose,
    )

    ctx.invoke(
        make_hybrid_mbr,
        boot_device=boot_device,
        verbose=verbose,
    )

    _mount = hs.Command("mount")

    os.makedirs(mount_path_boot, exist_ok=True)
    boot_partition_path = add_partition_number_to_device(
        device=boot_device,
        partition_number=3,
    )
    assert not path_is_mounted(mount_path_boot)
    _mount(
        boot_partition_path.as_posix(),
        mount_path_boot.as_posix(),
        _out=sys.stdout,
        _err=sys.stderr,
    )
    assert path_is_mounted(mount_path_boot)

    os.makedirs(mount_path_boot_efi, exist_ok=True)
    efi_partition_path = add_partition_number_to_device(
        device=boot_device,
        partition_number=2,
    )
    assert not path_is_mounted(mount_path_boot_efi)
    _mount(
        efi_partition_path.as_posix(),
        mount_path_boot_efi.as_posix(),
        _out=sys.stdout,
        _err=sys.stderr,
    )
    assert path_is_mounted(mount_path_boot_efi)

    install_grub(boot_device, skip_uefi=skip_uefi, debug_grub=debug_grub)

    if _compile_kernel:
        compile_and_install_kernel(
            fix=True,
            warn_only=False,
            symlink_config=False,
            configure=configure_kernel,
            force=force,
            no_check_boot=True,
        )
    else:
        install_compiled_kernel()

    generate_grub_config(path=Path("/boot/grub/grub.cfg"), replace=True)


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
@click.option("--skip-uefi", is_flag=True, required=False)
@click.option("--debug-grub", is_flag=True, required=False)
@click_add_options(click_global_options)
@click.pass_context
def _install_grub(
    ctx: click.Context,
    *,
    boot_device: Path,
    skip_uefi: bool,
    debug_grub: bool,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    install_grub(
        boot_device=boot_device,
        skip_uefi=skip_uefi,
        debug_grub=debug_grub,
    )


@cli.command("regenerate-grub-config")
@click.argument(
    "path",
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
def _regenerate_grub_config(
    ctx: click.Context,
    *,
    path: Path,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    generate_grub_config(path=path, replace=True)
