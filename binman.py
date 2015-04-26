#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  binman.py - eopkg repository maintainence
#  Warning: Still work in progress, missing publish/snapshot functionality!
#  
#  Copyright 2015 Ikey Doherty <ikey@solus-project.com>
#  
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
import sys
import os
import argparse
import shutil
import collections
import pisi
import glob
import cPickle as pickle

# Yes - that really is hardcoded right now.
basedir = "./repo"

class RepoPackage:
    ''' Exists solely to enable pickling magics '''
    filename = None
    pkg = None
    source = None
    release = None

    def __init__(self, pkg, filename):
        self.filename = filename
        self.pkg = pkg
        self.source = self.pkg.source.name
        self.release = int(self.pkg.package.history[0].release)

    def __eq__(self, other):
        if self.filename == other.filename and self.source == other.filename and self.release == other.release:
            return True
        return False

    def get_release(self):
        return self.release

class RepoCollection:

    db = None

    def __init__(self):
        self.db = dict()

    def append(self, pkg):
        ''' Append this package to the repo collection '''
        if not pkg.source in self.db:
            self.db[pkg.source] = list()
        if not pkg in self.db[pkg.source]:
            self.db[pkg.source].append(pkg)
        else:
            print "Already there :o"

    def remove(self, pkg):
        ''' Remove this package from the repo collection '''
        if not pkg.source in self.db:
            return
        self.db[pkg.source].remove(pkg)

    def __hasitem__(self, pkg):
        ''' Passing a .eopkg to determine if we have it. '''
        if not pkg.source in self.db:
            return False
        return pkg in self.db[pkg.source]

    def __contains__(self, sname):
        if sname in self.db:
            return True
        return False

    def __getitem__(self, sname):
        ''' Return packages for this source name '''
        if not sname in self.db:
            raise KeyError("No such key: %s" % sname)
        return self.db[sname]

class BinMan:

    repodbs = dict()
    altered = list()
    needdelta = list()
    lastrepo = None

    def get_args(self):
        return sys.argv[2:3]

    def get_subargs(self):
        return sys.argv[3:]

    def has_args(self):
        return len(self.get_args()) > 0

    def mark_altered(self, name):
        if not name in self.altered:
            self.altered.append(name)

    def __init__(self):
        ''' Construct a new BinMan '''
        helps = collections.OrderedDict()
        helps["add"] = "Add package(s) to repository"
        helps["clone"] = "Clone a repository"
        helps["copy-source"] = "Copy package by source name"
        helps["create-repo"] =  "Create new repository"
        helps["delta"] = "Create package deltas"
        helps["list-repos"] = "List repositories"
        helps["pull"] = "Pull from one repo into another"
        helps["remove-repo"] =  "Remove existing repository"
        helps["remove-source"] = "Remove package by source name"
        helps["help"] =  "Print this help message"
        biggest = sorted([len(x) for x in helps.keys()], reverse=True)[0]
        hlptxt = ""
        biggest += 4
        for k in helps:
            hlptxt += k.rjust(biggest) + " - " + helps[k] + "\n"

        parser = argparse.ArgumentParser(description="eopkg repository management",
            usage="%s <command> [arguments]\n\n%s" % (sys.argv[0],hlptxt))
        self.p = parser
        parser.add_argument("command", help=argparse.SUPPRESS)

        if len(sys.argv) < 2:
            parser.print_help()
            sys.exit(0)

        args = parser.parse_args(sys.argv[1:2])
        if not hasattr(args, 'command'):
            sys.exit(1)
        command = args.command.replace("-","_")
        if not hasattr(self, command) or args.command not in helps:
            print "Unknown command: %s" % command
            sys.exit(1)
        getattr(self, command)()

        if len(self.altered) > 0:
            print "Updating altered repositories"
            for repo in self.altered:
                self._update_repo(repo)

    def _update_repo(self, repo):
        dirn = self._get_repo_dir(repo)
        if not self._is_repo(dirn):
            print "%s is not a valid repo" % repo
            return

        if self.lastrepo and len(self.needdelta) > 0:
            print "Reproducing deltas due to invalidation"
            for name in self.needdelta:
                self._create_delta(self.lastrepo, name)

        olddir = os.getcwd()
        os.chdir(dirn)
        pisi.api.index(["."],
                       output=os.path.join(dirn, "eopkg-index.xml"),
                       skip_sources=True,
                       skip_signing=True, # TODO: Add signing support
                       compression=pisi.file.File.COMPRESSION_TYPE_XZ)
        os.chdir(olddir)

    def help(self):
        ''' Display help message, optionally for a given topic '''
        if not self.has_args():
            self.p.print_help()
            sys.exit(0)
        parser = argparse.ArgumentParser(description="Show help on a given topic")
        parser.add_argument("topic", help="Topic to display help on")
        args = parser.parse_args(self.get_args())
        topic = args.topic.replace("-","_")
        if not hasattr(self, topic):
            print "Unknown topic"
            sys.exit(1)
        getattr(self, topic)(True)

    def _is_repo(self, name):
        ''' Determine if path contains a repo '''
        return os.path.exists(self._get_repo_file(name))

    def _get_repo_file(self, name):
        ''' Get the repo file name '''
        return os.path.abspath(os.path.join(basedir, name, ".eopkg-repo"))

    def _get_repo_dir(self, name):
        ''' Get the repo name '''
        return os.path.abspath(os.path.dirname(self._get_repo_file(name)))

    def _get_repo_db_name(self, name):
        ''' Get the repo DB '''
        return os.path.abspath(os.path.join(basedir, name + ".db"))

    def _get_repo_db(self, name):
        ''' Get the repository database '''
        db = None
        if name in self.repodbs:
            return self.repodbs[name]
        if os.path.exists(self._get_repo_db_name(name)):
            try:
                f = open(self._get_repo_db_name(name), "rb")
                db = pickle.load(f)
                f.close()
            except Exception, e:
                print "Unable to load DB file: %s" % os.path.basename(self._get_repo_db_name(name))
                print e
                sys.exit(1)
            self.repodbs[name] = db
            return self.repodbs[name]
        else:
            self.repodbs[name] = RepoCollection()
            return self.repodbs[name]

    def _stuff_repo_db(self, name):
        if name not in self.repodbs:
            return
        db = self.repodbs[name]
        try:
            f = open(self._get_repo_db_name(name), "wb")
            pickle.dump(db, f)
            f.flush()
            f.close()
        except Exception, e:
            print "Unable to save DB file: %s" % os.path.basename(self._get_repo_db_name(name))
            print e
            sys.exit(1)

    def _touch(self, fname):
        ''' Simply create a file '''
        open(fname, 'a').close()

    def _get_pool_dir(self):
        ''' Return the pool directory '''
        return os.path.abspath(os.path.join(basedir, "pool"))

    def _get_pool_name(self, fpath):
        ''' Return the pool name for the input file '''
        return os.path.join(self._get_pool_dir(), os.path.basename(fpath))

    def _is_pooled(self, fpath):
        return os.path.exists(self._get_pool_name(fpath))

    def _get_repo_target(self, repo, fpath):
        ''' Get the target in the repo for this file. '''
        pkg = None
        bpath = fpath
        if isinstance(fpath, RepoPackage):
            pkg = fpath.pkg
            bpath = fpath.filename
        else:
            pkg,files = pisi.api.info(fpath)
            bpath = os.path.basename(fpath)
        dirn = pkg.source.name
        if dirn.startswith("lib"):
            dirn = dirn[:4]
        else:
            dirn = dirn[0]
        return os.path.join(self._get_repo_dir(repo), dirn, pkg.source.name, bpath)

    def _create_repo(self, name):
        ''' Helper to create a new repo '''
        try:
            os.makedirs(os.path.dirname(self._get_repo_file(name)))
            self._touch(self._get_repo_file(name))
        except Exception, e:
            print "Unable to create repo: %s" % name
            print e
            sys.exit(1)

    def create_repo(self, showhelp = False):
        ''' Create a new repository '''
        parser = argparse.ArgumentParser(description="Create a new repository")
        parser.add_argument("repo", help="Name of the new repository")
        if showhelp:
            parser.print_help()
            sys.exit(0)

        args = parser.parse_args(self.get_args())
        name = args.repo
        if self._is_repo(name):
            print "%s already exists - aborting" % name
            sys.exit(1)
        elif os.path.exists(name):
            print "%s exists and is not a repo" % name
            sys.exit(1)
        self._create_repo(name)

    def remove_repo(self, showhelp = False):
        ''' Remove a repository '''
        parser = argparse.ArgumentParser(description="Remove repository")
        parser.add_argument("repo", help="Name of the repository")
        if showhelp:
            parser.print_help()
            sys.exit(0)
        args = parser.parse_args(self.get_args())

        name = args.repo
        if not self._is_repo(name):
            print "Not removing non-repo %s" % name
            return

        db = self._get_repo_db(name)
        for source in db.db:
            print source
            pkgs = db[source]
            i = 0
            for pkg in list(db[source]):
                self._remove_package(name, pkg, bypass=True)
                i += 1

        dirn = self._get_repo_dir(name)
        try:
            os.unlink(os.path.join(dirn, ".eopkg-repo"))
            ifiles = glob.glob(os.path.join(dirn, "eopkg-index*"))
            for f in ifiles:
                os.unlink(f)
            os.rmdir(dirn)
            self.repodbs.pop(name, None)
            os.unlink(self._get_repo_db_name(name))
        except Exception, e:
            print "Unable to delete repo directory: %s" % dirn
            print e
            sys.exit(1)

        print "Successfully removed repository: %s" % name

    def get_delta_filename(self, pkg1, pkg2):
        ''' Determine end name of delta file '''
        delta_name = "-".join((pkg2.name, pkg1.release, pkg2.release,
           pkg2.distributionRelease, pkg2.architecture)) + pisi.context.const.delta_package_suffix
        return delta_name

    def get_delta_to_glob(self, pkg):
        ''' Determine end name of delta file '''
        delta_name = "-".join((pkg.name, pkg.release, "*",
           pkg.distributionRelease, pkg.architecture)) + pisi.context.const.delta_package_suffix
        return delta_name

    def get_delta_from_glob(self, pkg):
        ''' Determine end name of delta file '''
        delta_name = "-".join((pkg.name, "*", pkg.release,
           pkg.distributionRelease, pkg.architecture)) + pisi.context.const.delta_package_suffix
        return delta_name

    def _create_delta(self, repo, source):
        ''' Create delta for the given source name within a particular repo '''
        olddir = os.getcwd()
        if not self._is_repo(repo):
            raise RuntimeError("Should not be reached, aborting")

        db = self._get_repo_db(repo)
        if not source in db.db:
            return

        pkgs = db.db[source]
        # Attempt to gen uniq package names..
        pkg_names = dict()
        for pkg in pkgs:
            if pkg.pkg.package.name not in pkg_names:
                pkg_names[pkg.pkg.package.name] = list()
            pkg_names[pkg.pkg.package.name].append(pkg)
        for pkgn in pkg_names:
            bins = pkg_names[pkgn]
            bins = sorted(bins, key=RepoPackage.get_release, reverse=True)
            if len(bins) < 2:
                continue
            top = bins[0]
            remain = bins[1:]
            for i in remain:
                dname = self.get_delta_filename(i.pkg.package, top.pkg.package)
                deltadir = os.path.dirname(self._get_repo_target(repo, top))
                deltapath = os.path.join(deltadir, dname)
                if not os.path.exists(deltapath):
                    print "Creating delta: %s" % dname
                    ptgt = self._get_pool_name(deltapath)
                    if os.path.exists(ptgt):
                        print "Using cached delta: %s" % dname
                        try:
                            os.link(ptgt, deltapath)
                        except Exception, e:
                            print "Unable to link pool delta: %s" % dname
                            print e
                        continue
                    os.chdir(deltadir)
                    pkgs = pisi.operations.delta.create_delta_package(i.filename, top.filename)
                    if not pkgs or len(pkgs) == 0:
                        print "No delta possible for %s-%s" % (i.pkg.package.name, i.pkg.package.version)
                    else:
                        for d in pkgs:
                            try:
                                dpath = os.path.join(deltadir, d)
                                print dpath
                                print ptgt
                                os.link(dpath, ptgt)
                            except Exception, e:
                                print "Unable to pool delta: %s" % d
                                print e
                    os.chdir(olddir)

    def delta(self, showhelp = False):
        ''' Create deltas in the given repo '''
        parser = argparse.ArgumentParser(description="Create deltas for <repo>")
        parser.add_argument("repo", help="Name of repository")
        if showhelp:
            parser.print_help()
            sys.exit(0)
        args = parser.parse_args(self.get_args())

        name = args.repo
        if not self._is_repo(name):
            print "Not producing deltas for non-repo %s" % name
            sys.exit(1)
        db = self._get_repo_db(name)
        if len(db.db.keys()) == 0:
            print "No packages found in %s" % name
            sys.exit(0)

        for source in db.db:
            self._create_delta(name, source)

    def remove_source(self, showhelp = False):
        parser = argparse.ArgumentParser(description="Remove all packages from <repo> matching source name. Note that by using \"pkg==release\" syntax you can opt to remove only packages of a specific release number")
        parser.add_argument("repo", help="Name of the repository")
        parser.add_argument("--packages", help=argparse.SUPPRESS)
        if showhelp:
             parser.print_help()
             sys.exit(0)

        args,sargs = parser.parse_known_args(sys.argv[2:])
        repo = args.repo

        if len(sargs) < 1:
            print "Requires at least one source name"
            sys.exit(1)
        if not self._is_repo(repo):
            print "%s is not a valid repository" % dest
            sys.exit(1)


        removals = list()
        for name in sargs:
            rel = None
            if "==" in name:
                splits = name.split("==")
                name = splits[0]
                try:
                    rel = int(splits[1])
                except Exception, e:
                    print "%s is not a valid number" % splits[1]
                    sys.exit(1)
            if not name in self._get_repo_db(repo):
                print "%s does not exist in %s repo" % (name, repo)
                sys.exit(1)
            pkgs = self._get_repo_db(repo)[name]
            match = pkgs
            if rel:
                match = [x for x in pkgs if int(x.release) == rel]
                if not match or len(match) == 0:
                    print "No matches found for %s==%s" % (name,rel)
                    sys.exit(1)
            removals.extend(match)
        self.mark_altered(repo)
        for removal in removals:
            self._remove_package(repo, removal, bypass=True)
        if len(self._get_repo_db(repo).db[name]) == 0:
            self._get_repo_db(repo).db.pop(name, None)
        self._stuff_repo_db(repo)

    def pull(self, showhelp = False):
        ''' Update src repo from dst, basically a partial mass copy-src '''
        parser = argparse.ArgumentParser(description="Pull changes from <origin> repo into <clone>")
        parser.add_argument("clone", help="Name of the cloned repository")
        parser.add_argument("origin", help="Name of the source repository")
        if showhelp:
             parser.print_help()
             sys.exit(0)

        args = parser.parse_args(sys.argv[2:])
        origin = args.origin
        clone = args.clone

        if not self._is_repo(origin):
            print "Origin %s does not exist" % origin
            sys.exit(1)
        if not self._is_repo(clone):
            print "Clone %s does not exist" % clone
            sys.exit(1)

        olddb = self._get_repo_db(clone)
        newdb = self._get_repo_db(origin)

        updates = 0
        for source in newdb.db:
            pkgs = sorted(newdb[source], key=RepoPackage.get_release, reverse=True)
            if source not in olddb.db:
                print "Pulling new package source: %s" % source
                self._add_package(clone, pkgs[0])
                updates += 1
            else:
                oldpkgs = sorted(olddb[source], key=RepoPackage.get_release, reverse=True)
                nrel = pkgs[0].release
                orel = oldpkgs[0].release
                if (nrel > orel):
                    print "Updating %s from %s-%s to %s-%s" % (source, oldpkgs[0].pkg.package.history[0].version, orel, pkgs[0].pkg.package.history[0].version, nrel)
                    self._add_package(clone, pkgs[0])
                    updates += 1
        if updates > 0:
            self._stuff_repo_db(clone)
        else:
            print "Everything up to date"

    def clone(self, showhelp = False):
        ''' Clone repo from src to dst, basically a mass copy-src '''
        parser = argparse.ArgumentParser(description="Clone one repository, creating a new identical snapshot")
        parser.add_argument("src", help="Name of the source repository")
        parser.add_argument("dest", help="Name of the new repository")
        parser.add_argument("-a", "--all-versions", help="Copy all versions", action="store_true")
        parser.add_argument("--packages", help=argparse.SUPPRESS)
        if showhelp:
             parser.print_help()
             sys.exit(0)

        args = parser.parse_args(sys.argv[2:])
        src = args.src
        dest = args.dest

        if not self._is_repo(src):
            print "%s is not a valid repository" % dest
            sys.exit(1)
        if os.path.exists(self._get_repo_dir(dest)):
            print "%s exists - aborting" % dest
            sys.exit(1)

        db = self._get_repo_db(src)
        if len(db.db.keys()) == 0:
            print "%s is empty, cannot clone" % src
            sys.exit(1)

        self._create_repo(dest)

        for source in db.db:
            pkgs = db[source]

            copies = pkgs
            if not args.all_versions:
                releases = sorted([int(x.release) for x in pkgs], reverse=True)
                copies = [x for x in pkgs if int(x.release) == releases[0]]
            for copy in copies:
                tgt = self._get_repo_target(dest, copy)
                if os.path.exists(tgt):
                    print "Skipping inclusion of already included %s" % copy.pkg.package.name
                else:
                    if not self._add_package(dest, copy):
                        print "Failed to clone: %s" % tgt
                        sys.exit(1)
                    else:
                        print "add: %s" % copy.pkg.package.name
        self.mark_altered(dest)
        self._stuff_repo_db(dest)

    def copy_source(self, showhelp = False):
        ''' Copy package from src to dst '''
        parser = argparse.ArgumentParser(description="Copy package using source name")
        parser.add_argument("src", help="Name of the source repository")
        parser.add_argument("dest", help="Name of the dest repository")
        parser.add_argument("-a", "--all-versions", help="Copy all versions", action="store_true")
        parser.add_argument("--packages", help=argparse.SUPPRESS)
        if showhelp:
             parser.print_help()
             sys.exit(0)

        args,sargs = parser.parse_known_args(sys.argv[2:])
        src = args.src
        dest = args.dest

        if len(sargs) < 1:
            print "Requires at least one source name"
            sys.exit(1)
        if not self._is_repo(src):
            print "%s is not a valid repository" % dest
            sys.exit(1)
        if not self._is_repo(dest):
            print "%s is not a valid repository" % dest
            sys.exit(1)

        for name in sargs:
            if not name in self._get_repo_db(src):
                print "%s does not exist in %s repo" % (name, src)
                sys.exit(1)
        for name in sargs:
            pkgs = self._get_repo_db(src)[name]

            copies = pkgs
            if not args.all_versions:
                releases = sorted([int(x.release) for x in pkgs], reverse=True)
                copies = [x for x in pkgs if int(x.release) == releases[0]]
            for copy in copies:
                tgt = self._get_repo_target(dest, copy)
                if os.path.exists(tgt):
                    print "Skipping inclusion of already included %s" % copy.pkg.package.name
                else:
                    if not self._add_package(dest, copy):
                        print "Failed to copy-source: %s" % tgt
                        sys.exit(1)
                    else:
                        print "Copy-source complete: %s" % copy.pkg.package.name
        self.mark_altered(dest)
        self._stuff_repo_db(dest)

    def _get_repos(self):
        if not os.path.exists(basedir):
            return None
        ret = list()
        try:
            for k in os.listdir(basedir):
                if os.path.exists(os.path.join(basedir, k, ".eopkg-repo")):
                    ret.append(k)
        except Exception, e:
            return None
        return ret

    def list_repos(self, showhelp = False):
        parser = argparse.ArgumentParser(description="List repositories")
        parser.add_argument("--dummy", help=argparse.SUPPRESS)
        ''' List the known repositories '''
        if showhelp:
            parser.print_help()
            sys.exit(0)
        repos = self._get_repos()
        if not repos or len(repos) == 0:
            print "No repositories found"
            sys.exit(0)
        print "Repositories:\n"
        for p in repos:
            print "\t%s" % p

    def _add_package(self, repo, pkg):
        ''' Add the given package into our repo '''
        repofile = self._get_repo_target(repo, pkg)
        repodir = os.path.dirname(repofile)

        if os.path.exists(repofile):
            print "_add_package should not be reached for existing file"
            sys.exit(1)

        db = self._get_repo_db(repo)
        pobj = None
        if isinstance(pkg, str):
            meta,files = pisi.api.info(pkg)
            pobj = RepoPackage(meta, os.path.basename(pkg))
        else:
            pobj = pkg
        db.append(pobj)

        if not os.path.exists(repodir):
            try:
                os.makedirs(repodir)
            except Exception, e:
                print "Unable to create %s" % repodir
                print e
                return False
        if not self._is_pooled(pobj.filename):
            if isinstance(pkg, RepoPackage):
                print "Local package not pooled - fatal"
                sys.exit(1)
            print "Pooling: %s" % pobj.filename
            try:
                if not os.path.exists(self._get_pool_dir()):
                    os.makedirs(self._get_pool_dir())

                shutil.copy2(pkg, self._get_pool_name(pobj.filename))
            except Exception, e:
                print "Unable to pool: %s\n" % pobj.filename
                return False
        else:
            print "Using %s from pool" % pobj.filename

        try:
            os.link(self._get_pool_name(pobj.filename), repofile)
            print "Imported %s" % pobj.filename
        except Exception, e:
            print "Unable to link from pool: %s" % pobj.filename
            return False
        self.mark_altered(repo)

        return True

    def _remove_package(self, repo, pkg, bypass=False):
        ''' Remove the given package from a repo '''
        repofile = self._get_repo_target(repo, pkg)
        db = self._get_repo_db(repo)

        try:
            os.unlink(repofile)
            pkgdir = os.path.dirname(repofile)
            pkgdir_p = os.path.dirname(pkgdir)
            db.remove(pkg)

            globTo = os.path.join(pkgdir, self.get_delta_to_glob(pkg.pkg.package))
            globFrom = os.path.join(pkgdir, self.get_delta_from_glob(pkg.pkg.package))

            kills = list()
            kills.extend(glob.glob(globTo))
            kills.extend(glob.glob(globFrom))
            for kill in kills:
                print "Removing invalid delta:%s" % kill
                try:
                    os.unlink(kill)
                except Exception, e:
                    print "Unable to remove: %s" % kill
                    print e
                if pkg.source not in self.needdelta and not bypass:
                    self.needdelta.append(pkg.source)
                    self.lastrepo = repo
                self._clean_pool(self._get_pool_name(kill))

            if len(os.listdir(pkgdir)) == 0:
                print "Removing package directory: %s" % pkgdir
                os.rmdir(pkgdir)
            if len(os.listdir(pkgdir_p)) == 0:
                print "Removing package parent directory: %s" % pkgdir_p
                os.rmdir(pkgdir_p)
        except Exception, e:
            print "Unable to remove package: %s" % repofile
            print e
            return False
        finally:
            if not bypass:
                self._stuff_repo_db(repo)
        # Clean up pool
        self._clean_pool(pkg)
        return True

    def _clean_pool(self, pkg):
        names = [self._get_repo_target(x, pkg) for x in self._get_repos()]
        if not names or len(names) < 1:
            print "??"
            return
        existing = [x for x in names if os.path.exists(x)]
        if len(existing) == 0:
            pfile = self._get_pool_name(pkg) if isinstance(pkg, str) else self._get_pool_name(pkg.filename)
            print "Removing no-longer used pool file: %s" % pfile
            try:
                os.unlink(pfile)
            except Exception, e:
                print "Unable to remove pool file: %s" % pfile
                print e
                sys.exit(1)

    def add(self, showhelp=False):
        ''' Add packages to repository '''
        parser = argparse.ArgumentParser(description="Add package(s) to repository",
            usage="%s add <repo> [packages]" % sys.argv[0])
        parser.add_argument("repo", help="Name of the repository")
        parser.add_argument("--packages", help=argparse.SUPPRESS)
        if showhelp:
            parser.print_help()
            sys.exit(0)
        args = parser.parse_args(self.get_args())
        name = args.repo
        if not self._is_repo(name):
            print "Repository '%s' does not exist" % name
            sys.exit(1)

        if len(self.get_subargs()) < 1:
            print "No packages specified\n"
            parser.print_help()
            sys.exit(1)

        invalids = [x for x in self.get_subargs() if not os.path.exists(x) or not x.endswith(".eopkg")]
        if len(invalids) > 0:
            print "Invalid or missing: %s" % (", ".join([os.path.basename(x) for x in invalids]))
            sys.exit(1)

        for pkg in self.get_subargs():
            if not os.path.exists(self._get_repo_target(name, pkg)):
                print "Adding to %s: %s" % (name, pkg)
                if pkg.endswith(".delta.eopkg"):
                    print "Skipping delta: %s" % pkg
                    continue
                if not self._add_package(name, pkg):
                    print "Aborting due to failed add"
                    self._stuff_repo_db(name);
                    sys.exit(1)
            else:
                print "%s already in repo" % os.path.basename(pkg)
        self._stuff_repo_db(name)

if __name__ == "__main__":
    BinMan()