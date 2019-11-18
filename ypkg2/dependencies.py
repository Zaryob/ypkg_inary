#!/bin/true
# -*- coding: utf-8 -*-
#
#  This file is part of ypkg2
#
#  Copyright 2015-2017 Ikey Doherty <ikey@solus-project.com>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#

from . import console_ui
from inary.db.installdb import InstallDB
from inary.db.packagedb import PackageDB
from inary.db.filesdb import FilesDB
import os

# Provided historically for our pre-glvnd architecture.
# Technically speaking this isn't required anymore, but lets just
# play it safe for those directly using ypkg on old NVIDIA drivers.
ExceptionRules = [
    "libEGL.so",
    "libEGL.so.1",
    "libEGL.so.1.0.0",
    "libGLESv1_CM.so",
    "libGLESv1_CM.so.1",
    "libGLESv1_CM.so.1.1.0",
    "libGLESv2.so",
    "libGLESv2.so.2",
    "libGLESv2.so.2.0.0",
    "libGL.so",
    "libGL.so.1",
    "libGL.so.1.0.0",
    "libGL.so.1.2.0",
    "libglx.so",
    "libglx.so.1",
]


class DependencyResolver:

    idb = None
    pdb = None
    fdb = None

    global_rpaths = set()
    global_rpaths32 = set()
    global_kernels = dict()
    gene = None

    bindeps_cache = dict()
    bindeps_emul32 = dict()

    pkgconfig_cache = dict()
    pkgconfig32_cache = dict()

    files_cache = dict()

    kernel_cache = dict()

    deadends = dict()

    # Cached from packagedb
    pkgConfigs = None
    pkgConfigs32 = None

    def search_file(self, fname):
        if fname[0] == '/':
            fname = fname[1:]
        if fname in self.deadends:
            return None
        if self.fdb.has_file(fname):
            return self.fdb.get_file(fname)
        # Nasty file conflict crap happened on update and the filesdb
        # is now inconsistent ..
        ret = self.fdb.search_file(fname)
        if len(ret) == 1:
            return ret[0]
        # Just blacklist further lookups here
        self.deadends[fname] = 0
        return None

    def __init__(self):
        """ Allows us to do look ups on all packages """
        self.idb = InstallDB()
        self.pdb = PackageDB()
        self.fdb = FilesDB()


    def get_symbol_provider(self, info, symbol):
        """ Grab the symbol from the local packages """
        if info.emul32:
            tgtMap = self.global_sonames32
            rPaths = self.global_rpaths32
        else:
            tgtMap = self.global_sonames
            rPaths = self.global_rpaths

        if symbol in tgtMap:
            pkgname = tgtMap[symbol]
            return self.ctx.spec.get_package_name(pkgname)

        # Check if its in any rpath
        for rpath in rPaths:
            fpath = os.path.join(rpath, symbol)
            pkg = self.gene.get_file_owner(fpath)
            if pkg:
                return self.ctx.spec.get_package_name(pkg.name)
        return None

    def get_symbol_external(self, info, symbol, paths=None):
        """ Get the provider of the required symbol from the files database,
            i.e. installed binary dependencies
        """
        # Try a cached approach first.
        if info.emul32:
            if symbol in self.bindeps_emul32:
                return self.bindeps_emul32[symbol]
        else:
            if symbol in self.bindeps_cache:
                return self.bindeps_cache[symbol]

        if symbol in ExceptionRules:
            if info.emul32:
                return "libglvnd-32bit"
            else:
                return "libglvnd"

        if not paths:
            paths = ["/usr/lib64", "/usr/lib"]
            if info.emul32:
                paths = ["/usr/lib32", "/usr/lib", "/usr/lib64"]

            if info.rpaths:
                paths.extend(info.rpaths)

        pkg = None
        for path in paths:
            fpath = os.path.join(path, symbol)
            if not os.path.exists(fpath):
                continue
            lpkg = None
            if fpath in self.files_cache:
                lpkg = self.files_cache[fpath]
            else:
                pkg = self.search_file(fpath)
                if pkg:
                    lpkg = pkg[0]
            if lpkg:
                if info.emul32:
                    self.bindeps_emul32[symbol] = lpkg
                else:
                    self.bindeps_cache[symbol] = lpkg
                console_ui.emit_info("Dependency",
                                     "{} adds dependency on {} from {}".
                                     format(info.pretty, symbol, lpkg))

                # Populate a global files cache, basically there is a high
                # chance that each package depends on multiple things in a
                # single package.
                for file in self.idb.get_files(lpkg).list:
                    self.files_cache["/" + file.path] = lpkg
                return lpkg
        return None

    def handle_binary_deps(self, packageName, info):
        """ Handle direct binary dependencies """
        pkgName = self.ctx.spec.get_package_name(packageName)

        for sym in info.symbol_deps:
            r = self.get_symbol_provider(info, sym)
            if not r:
                r = self.get_symbol_external(info, sym)
                if not r:
                    print("Fatal: Unknown symbol: {}".format(sym))
                    continue
            # Don't self depend
            if pkgName == r:
                continue
            self.gene.packages[packageName].depend_packages.add(r)

    def get_kernel_provider(self, info, version):
        """ i.e. self dependency situation """
        if version in self.global_kernels:
            pkg = self.global_kernels[version]
            return self.ctx.spec.get_package_name(pkg)
        return None

    def get_kernel_external(self, info, version):
        """ Try to find the owning kernel for a version """
        if version in self.kernel_cache:
            return self.kernel_cache[version]

        paths = [
            "/usr/lib/kernel",
            "/usr/lib64/kernel"
        ]

        pkg = None
        for path in paths:
            # Special file in the main kernel package
            fpath = "{}/System.map-{}".format(path, version)
            if not os.path.exists(fpath):
                continue
            lpkg = None
            if fpath in self.files_cache:
                lpkg = self.files_cache[fpath]
            else:
                pkg = self.search_file(fpath)
                if pkg:
                    lpkg = pkg[0]
            if lpkg:
                self.kernel_cache[version] = lpkg
                console_ui.emit_info("Kernel",
                                     "{} adds module dependency on {} from {}".
                                     format(info.pretty, version, lpkg))

                # Populate a global files cache, basically there is a high
                # chance that each package depends on multiple things in a
                # single package.
                for file in self.idb.get_files(lpkg).list:
                    self.files_cache["/" + file.path] = lpkg
                return lpkg
        return None

    def handle_kernel_deps(self, packageName, info):
        """ Add dependency between packages due to kernel version """
        pkgName = self.ctx.spec.get_package_name(packageName)

        r = self.get_kernel_provider(info, info.dep_kernel)
        if not r:
            r = self.get_kernel_external(info, info.dep_kernel)
            if not r:
                print("Fatal: Unknown kernel: {}".format(sym))
                return
        # Don't self depend
        if pkgName == r:
            return
        self.gene.packages[packageName].depend_packages.add(r)

    def compute_for_packages(self, context, gene, packageSet):
        """ packageSet is a dict mapping here. """
        self.gene = gene
        self.packageSet = packageSet
        self.ctx = context

        # First iteration, collect the globals
        for packageName in packageSet:
            for info in packageSet[packageName]:
                if info.rpaths:
                    if info.emul32:
                        self.global_rpaths32.update(info.rpaths)
                    else:
                        self.global_rpaths.update(info.rpaths)
                if info.soname:
                    if info.emul32:
                        self.global_sonames32[info.soname] = packageName
                    else:
                        self.global_sonames[info.soname] = packageName
                if info.pkgconfig_name:
                    pcName = info.pkgconfig_name

                if info.prov_kernel:
                    self.global_kernels[info.prov_kernel] = packageName

        # Ok now find the dependencies
        for packageName in packageSet:
            for info in packageSet[packageName]:
                if info.symbol_deps:
                    self.handle_binary_deps(packageName, info)

                if info.soname_links:
                    self.handle_soname_links(packageName, info)

                if info.dep_kernel:
                    self.handle_kernel_deps(packageName, info)
        return True
