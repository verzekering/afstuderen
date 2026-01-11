#!/usr/bin/env python

# Thanks @takluyver for your cite2c install.py.
# Copyright (c) IPython Development Team.
# Distributed under the terms of the Modified BSD License.

from __future__ import print_function

import argparse


def install(user=False, symlink=False, enable=False):
    """The Jupyter Notebook widget has been removed from this release.
    This function is a no-op.

    Parameters
    ----------
    user: bool
        Install for current user instead of system-wide.
    symlink: bool
        Symlink instead of copy (for development).
    """
    print(
        "The Jupyter Notebook widget has been removed from this release.  Continuing."
    )


def uninstall():
    try:
        from notebook.nbextensions import uninstall_nbextension

        """Uninstall the widget nbextension from user and system locations
        """
        print("Uninstalling prior versions of arcgis widget")
        uninstall_nbextension("arcgis", user=True)
        uninstall_nbextension("arcgis", user=False)
    except:
        print(
            "Failed to automatically remove prior versions.\nManually uninstall any prior version of arcgis widget using:\n\t`jupyter nbextension uninstall arcgis --user` and \n\t`jupyter nbextension uninstall arcgis`"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Installs the ArcGIS IPython widgets")
    parser.add_argument(
        "-u",
        "--user",
        help="Install as current user instead of system-wide",
        action="store_true",
    )
    parser.add_argument(
        "-s", "--symlink", help="Symlink instead of copying files", action="store_true"
    )
    parser.add_argument(
        "-r",
        "--remove",
        help="Remove i.e. uninstall the extension",
        action="store_true",
    )
    args = parser.parse_args()

    if args.remove:
        uninstall()
    else:
        install(user=args.user, symlink=args.symlink)
