#!/bin/true
# -*- coding: utf-8 -*-
#
#  This file is part of ypkg2
#
#  Copyright 2015-2016 Ikey Doherty <ikey@solus-project.com>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#

from . import console_ui
import magic
import re
import os
import subprocess
import shutil
import multiprocessing

global share_ctx


v_dyn = re.compile(r"ELF (64|32)\-bit LSB shared object,")
v_bin = re.compile(r"ELF (64|32)\-bit LSB executable,")
v_rel = re.compile(r"ELF (64|32)\-bit LSB relocatable,")
shared_lib = re.compile(r".*Shared library: \[(.*)\].*")
r_path = re.compile(r".*Library rpath: \[(.*)\].*")
r_soname = re.compile(r".*Library soname: \[(.*)\].*")


def strip_file(context, pretty, file, magic_string, mode=None):
    """ Schedule a strip, basically. """
    if not context.spec.pkg_strip:
        return
    exports = ["LC_ALL=C"]
    if context.spec.pkg_optimize == "speed":
        exports.extend([
            "AR=\"gcc-ar\"",
            "RANLIB=\"gcc-ranlib\"",
            "NM=\"gcc-nm\""])

    cmd = "{} strip {} \"{}\""
    flags = ""
    if mode == "shared":
        flags = "--strip-unneeded"
    elif mode == "ko":
        flags = "-g --strip-unneeded"
    elif mode == "ar":
        flags = "--strip-debug"
    try:
        s = " ".join(exports)
        subprocess.check_call(cmd.format(s, flags, file), shell=True)
        console_ui.emit_info("Stripped", pretty)
    except Exception as e:
        console_ui.emit_warning("Strip", "Failed to strip '{}'".
                                format(pretty))
        print(e)


def get_debug_path(context, file, magic_string):
    """ Grab the NT_GNU_BUILD_ID """
    cmd = "LC_ALL=C readelf -n \"{}\"".format(file)
    try:
        lines = subprocess.check_output(cmd, shell=True)
    except Exception as e:
        return None

    for line in lines.split("\n"):
        if "Build ID:" not in line:
            continue
        v = line.split(":")[1].strip()

        libdir = "/usr/lib"
        if "ELF 32" in magic_string:
            libdir = "/usr/lib32"

        path = os.path.join(libdir, "debug", ".build-id", v[0:2], v[2:])
        return path + ".debug"
    return None


def examine_file(*args):
    global share_ctx
    package = args[0]
    pretty = args[1]
    file = args[2]
    mgs = args[3]

    context = share_ctx

    if v_dyn.match(mgs):
        # Get soname, direct deps and strip
        store_debug(context, pretty, file, mgs)
        strip_file(context, pretty, file, mgs, mode="shared")
    elif v_bin.match(mgs):
        # Get direct deps, and strip
        store_debug(context, pretty, file, mgs)
        strip_file(context, pretty, file, mgs, mode="executable")
    elif v_rel.match(mgs):
        # Kernel object in all probability
        if file.endswith(".ko"):
            store_debug(context, pretty, file, mgs)
            strip_file(context, pretty, file, mgs, mode="ko")
    elif mgs == "current ar archive":
        # Strip only.
        strip_file(context, pretty, file, mgs, mode="ar")
    return True


def store_debug(context, pretty, file, magic_string):
    if not context.can_dbginfo:
        return

    did = get_debug_path(context, file, magic_string)

    if did is None:
        if "ELF 32" in magic_string:
            did = "/usr/lib32/debug/{}.debug".format(pretty)
        else:
            did = "/usr/lib/debug/{}.debug".format(pretty)

    did_full = os.path.join(context.get_install_dir(), did[1:])

    dirs = os.path.dirname(did_full)
    if not os.path.exists(dirs):
        try:
            os.makedirs(dirs, mode=00755)
        except Exception as e:
            console_ui.emit_error("Debug", "Failed to make directory")
            print e
            return

    cmd = "objcopy --only-keep-debug \"{}\" \"{}\"".format(file, did_full)
    try:
        subprocess.check_call(cmd, shell=True)
    except Exception as e:
        console_ui.emit_warning("objcopy", "Failed --only-keep-debug")
        return
    cmd = "objcopy --add-gnu-debuglink=\"{}\" \"{}\"".format(did_full,
                                                             file)
    try:
        subprocess.check_call(cmd, shell=True)
    except Exception as e:
        console_ui.emit_warning("objcopy", "Failed --add-gnu-debuglink")
        return


class PackageExaminer:
    """ Responsible for identifying files suitable for further examination,
        such as those that should be removed, checked for dependencies,
        providers, and even those that should be stripped
    """

    def __init__(self):
        self.libtool_file = re.compile("libtool library file, ASCII text.*")

    def should_nuke_file(self, pretty, file, mgs):
        # it's not that we hate.. Actually, no, we do. We hate you libtool.
        if self.libtool_file.match(mgs):
            return True
        if pretty == "/usr/share/info/dir":
            return True
        return False

    def file_is_of_interest(self, mgs):
        """ So we can keep our list of things to check low """
        if v_dyn.match(mgs) or v_bin.match(mgs) or v_rel.match(mgs):
            return True
        return False

    def examine_package(self, context, package):
        """ Examine the given package and update symbols, etc. """
        install_dir = context.get_install_dir()

        global share_ctx

        share_ctx = context

        # Right now we actually only care about magic matching
        removed = set()

        pool = multiprocessing.Pool()
        results = list()

        for file in package.emit_files():
            if file[0] == '/':
                file = file[1:]
            fpath = os.path.join(install_dir, file)
            try:
                mgs = magic.from_file(fpath)
            except Exception as e:
                print(e)
                continue
            if self.should_nuke_file("/" + file, fpath, mgs):
                try:
                    if os.path.isfile(fpath):
                        os.unlink(fpath)
                    else:
                        shutil.rmtree(fpath)
                except Exception as e:
                    console_ui.emit_error("Clean", "Failed to remove unwanted"
                                          "file: {}".format(e))
                    return False
                console_ui.emit_info("Clean", "Removed unwanted file: {}".
                                     format("/" + file))
                removed.add("/" + file)

            if not self.file_is_of_interest(mgs):
                continue
            # Handle this asynchronously
            results.append(pool.apply_async(examine_file, [
                           package, "/" + file, fpath, mgs],
                           callback=None))

        pool.close()
        pool.join()

        # TODO: Grab new dependencies from the examine operation and apply
        for i in results:
            b = i.get()
            if not b:
                return False

        for r in removed:
            package.remove_file(r)
        return True

    def examine_packages(self, context, packages):
        """ Examine all packages, in order to update dependencies, etc """
        console_ui.emit_info("Examine", "Examining packages")
        for package in packages:
            if not self.examine_package(context, package):
                return False

        return True