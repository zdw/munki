#!/usr/bin/python
# encoding: utf-8
#
# Copyright 2009-2010 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
munkicommon

Created by Greg Neagle on 2008-11-18.

Common functions used by the munki tools.
"""

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib2
from distutils import version
from xml.dom import minidom

import munkistatus
import FoundationPlist


MANAGED_INSTALLS_PLIST_PATH = '/Library/Preferences/ManagedInstalls.plist'
MANAGED_INSTALLS_PLIST_PATH_NO_EXT = '/Library/Preferences/ManagedInstalls'
# Relative path of secure config plist file to root of ManagedInstallDir.
SECURE_CONFIG_PLIST_REL_PATH = 'Secure/SecureConfig.plist'
ADDITIONAL_HTTP_HEADERS_KEY = 'AdditionalHttpHeaders'


class Error(Exception):
    """Class for domain specific exceptions."""


class PreferencesError(Error):
    """There was an error reading the preferences plist."""


class VerifyFilePermissionsError(Error):
    """There was an error verifying file permissions."""


class InsecureFilePermissionsError(VerifyFilePermissionsError):
    """The permissions of the specified file are insecure."""


def get_version():
    """Returns version of munkitools"""
    return '0.6.0 Build 759'


# output and logging functions
def getsteps(num_of_steps, limit):
    """
    Helper function for display_percent_done
    """
    steps = []
    current = 0.0
    for i in range(0, num_of_steps):
        if i == num_of_steps-1:
            steps.append(int(round(limit)))
        else:
            steps.append(int(round(current)))
        current += float(limit)/float(num_of_steps-1)
    return steps


def display_percent_done(current, maximum):
    """
    Mimics the command-line progress meter seen in some
    of Apple's tools (like softwareupdate), or tells
    MunkiStatus to display percent done via progress bar.
    """
    if munkistatusoutput:
        step = getsteps(21, maximum)
        if current in step:
            if current == maximum:
                percentdone = 100
            else:
                percentdone = int(float(current)/float(maximum)*100)
            munkistatus.percent(str(percentdone))
    elif verbose > 1:
        step = getsteps(16, maximum)
        output = ''
        indicator = ['\t0', '.', '.', '20', '.', '.', '40', '.', '.',
                     '60', '.', '.', '80', '.', '.', '100\n']
        for i in range(0, 16):
            if current >= step[i]:
                output += indicator[i]
        if output:
            sys.stdout.write('\r' + output)
            sys.stdout.flush()


def display_status(msg):
    """
    Displays major status messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    log(msg)
    if munkistatusoutput:
        munkistatus.detail(msg)
    elif verbose > 0:
        if msg.endswith('.') or msg.endswith(u'…'):
            print '%s' % msg.encode('UTF-8')
        else:
            print '%s...' % msg.encode('UTF-8')
        sys.stdout.flush()


def display_info(msg):
    """
    Displays info messages.
    Not displayed in MunkiStatus.
    """
    log(msg)
    if munkistatusoutput:
        pass
    elif verbose > 0:
        print msg.encode('UTF-8')
        sys.stdout.flush()


def display_detail(msg):
    """
    Displays minor info messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    These are usually logged only, but can be printed to
    stdout if verbose is set to 2 or higher
    """
    if munkistatusoutput:
        pass
    elif verbose > 1:
        print msg.encode('UTF-8')
        sys.stdout.flush()
    if pref('LoggingLevel') > 0:
        log(msg)


def display_debug1(msg):
    """
    Displays debug messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    if munkistatusoutput:
        pass
    elif verbose > 2:
        print msg.encode('UTF-8')
        sys.stdout.flush()
    if pref('LoggingLevel') > 1:
        log('DEBUG1: %s' % msg)


def display_debug2(msg):
    """
    Displays debug messages, formatting as needed
    for verbose/non-verbose and munkistatus-style output.
    """
    if munkistatusoutput:
        pass
    elif verbose > 3:
        print msg.encode('UTF-8')
    if pref('LoggingLevel') > 2:
        log('DEBUG2: %s' % msg)


def reset_warnings():
    """Rotate our warnings log."""
    warningsfile = os.path.join(os.path.dirname(pref('LogFile')),
                                                'warnings.log')
    if os.path.exists(warningsfile):
        rotatelog(warningsfile)


def display_warning(msg):
    """
    Prints warning msgs to stderr and the log
    """
    warning = 'WARNING: %s' % msg
    print >> sys.stderr, warning.encode('UTF-8')
    log(warning)
    # append this warning to our warnings log
    log(warning, 'warnings.log')
    # collect the warning for later reporting
    report['Warnings'].append(msg)


def reset_errors():
    """Rotate our errors.log"""
    errorsfile = os.path.join(os.path.dirname(pref('LogFile')), 'errors.log')
    if os.path.exists(errorsfile):
        rotatelog(errorsfile)


def display_error(msg):
    """
    Prints msg to stderr and the log
    """
    errmsg = 'ERROR: %s' % msg
    print >> sys.stderr, errmsg.encode('UTF-8')
    log(errmsg)
    # append this error to our errors log
    log(errmsg, 'errors.log')
    # collect the errors for later reporting
    report['Errors'].append(msg)


def log(msg, logname=''):
    """Generic logging function"""
    # date/time format string
    formatstr = '%b %d %H:%M:%S'
    if not logname:
        # use our regular logfile
        logpath = pref('LogFile')
    else:
        logpath = os.path.join(os.path.dirname(pref('LogFile')), logname)
    try:
        fileobj = open(logpath, mode='a', buffering=1)
        try:
            print >> fileobj, time.strftime(formatstr), msg.encode('UTF-8')
        except (OSError, IOError):
            pass
        fileobj.close()
    except (OSError, IOError):
        pass


def rotatelog(logname=''):
    """Rotate a log"""
    if not logname:
        # use our regular logfile
        logpath = pref('LogFile')
    else:
        logpath = os.path.join(os.path.dirname(pref('LogFile')), logname)
    if os.path.exists(logpath):
        for i in range(3, -1, -1):
            try:
                os.unlink(logpath + '.' + str(i + 1))
            except (OSError, IOError):
                pass
            try:
                os.rename(logpath + '.' + str(i), logpath + '.' + str(i + 1))
            except (OSError, IOError):
                pass
        try:
            os.rename(logpath, logpath + '.0')
        except (OSError, IOError):
            pass


def rotate_main_log():
    """Rotate our main log"""
    if os.path.exists(pref('LogFile')):
        if os.path.getsize(pref('LogFile')) > 1000000:
            rotatelog(pref('LogFile'))


def printreportitem(label, value, indent=0):
    """Prints a report item in an 'attractive' way"""
    indentspace = '    '
    if type(value) == type(None):
        print indentspace*indent, '%s: !NONE!' % label
    elif type(value) == list or type(value).__name__ == 'NSCFArray':
        if label:
            print indentspace*indent, '%s:' % label
        index = 0
        for item in value:
            index += 1
            printreportitem(index, item, indent+1)
    elif type(value) == dict or type(value).__name__ == 'NSCFDictionary':
        if label:
            print indentspace*indent, '%s:' % label
        for subkey in value.keys():
            printreportitem(subkey, value[subkey], indent+1)
    else:
        print indentspace*indent, '%s: %s' % (label, value)


def printreport(reportdict):
    """Prints the report dictionary in a pretty(?) way"""
    for key in reportdict.keys():
        printreportitem(key, reportdict[key])


def savereport():
    """Save our report"""
    FoundationPlist.writePlist(report,
        os.path.join(pref('ManagedInstallDir'), 'ManagedInstallReport.plist'))


def archive_report():
    """Archive a report"""
    reportfile = os.path.join(pref('ManagedInstallDir'),
                              'ManagedInstallReport.plist')
    if os.path.exists(reportfile):
        modtime = os.stat(reportfile).st_mtime
        formatstr = '%Y-%m-%d-%H%M%S'
        archivename = 'ManagedInstallReport-' + \
                      time.strftime(formatstr,time.localtime(modtime)) + \
                       '.plist'
        archivepath = os.path.join(pref('ManagedInstallDir'), 'Archives')
        if not os.path.exists(archivepath):
            try:
                os.mkdir(archivepath)
            except (OSError, IOError):
                display_warning('Could not create report archive path.')
        try:
            os.rename(reportfile, os.path.join(archivepath, archivename))
        except (OSError, IOError):
            display_warning('Could not archive report.')
        # now keep number of archived reports to 100 or fewer
        proc = subprocess.Popen(['/bin/ls', '-t1', archivepath],
                                bufsize=1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (output, unused_err) = proc.communicate()
        if output:
            archiveitems = [item
                            for item in str(output).splitlines()
                            if item.startswith('ManagedInstallReport-')]
            if len(archiveitems) > 100:
                for item in archiveitems[100:]:
                    itempath = os.path.join(archivepath, item)
                    if os.path.isfile(itempath):
                        try:
                            os.unlink(itempath)
                        except (OSError, IOError):
                            display_warning('Could not remove archive item %s'
                                             % itempath)



# misc functions

def validPlist(path):
    """Uses plutil to determine if path contains a valid plist.
    Returns True or False."""
    retcode = subprocess.call(['/usr/bin/plutil', '-lint', '-s' , path])
    if retcode == 0:
        return True
    else:
        return False


def stopRequested():
    """Allows user to cancel operations when
    MunkiStatus is being used"""
    if munkistatusoutput:
        if munkistatus.getStopButtonState() == 1:
            log('### User stopped session ###')
            return True
    return False


def getconsoleuser():
    """Return console user"""
    from SystemConfiguration import SCDynamicStoreCopyConsoleUser
    cfuser = SCDynamicStoreCopyConsoleUser( None, None, None )
    return cfuser[0]


def currentGUIusers():
    """Gets a list of GUI users by parsing the output of /usr/bin/who"""
    gui_users = []
    proc = subprocess.Popen('/usr/bin/who', shell=False,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, unused_err) = proc.communicate()
    lines = str(output).splitlines()
    for line in lines:
        if 'console' in line:
            parts = line.split()
            gui_users.append(parts[0])

    return gui_users


def pythonScriptRunning(scriptname):
    """Returns Process ID for a running python script"""
    cmd = ['/bin/ps', '-eo', 'pid=,command=']
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, unused_err) = proc.communicate()
    mypid = os.getpid()
    lines = str(out).splitlines()
    for line in lines:
        (pid, process) = line.split(None, 1)
        # first look for Python processes
        if (process.find('MacOS/Python ') != -1 or
                                            process.find('python ') != -1):
            if process.find(scriptname) != -1:
                if int(pid) != int(mypid):
                    return pid

    return 0


def osascript(osastring):
    """Wrapper to run AppleScript commands"""
    cmd = ['/usr/bin/osascript', '-e', osastring]
    proc = subprocess.Popen(cmd, shell=False, bufsize=1,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if proc.returncode != 0:
        print >> sys.stderr, 'Error: ', err
    if out:
        return str(out).decode('UTF-8').rstrip('\n')


# dmg helpers

def mountdmg(dmgpath, use_shadow=False):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    If use_shadow is true, mount image with shadow file
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)
    cmd = ['/usr/bin/hdiutil', 'attach', dmgpath,
                '-mountRandom', '/tmp', '-nobrowse', '-plist']
    if use_shadow:
        cmd.append('-shadow')
    proc = subprocess.Popen(cmd,
                            bufsize=1, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (pliststr, err) = proc.communicate()
    if proc.returncode:
        display_error('Error: "%s" while mounting %s.' % (err, dmgname))
    if pliststr:
        plist = FoundationPlist.readPlistFromString(pliststr)
        for entity in plist['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints


def unmountdmg(mountpoint):
    """
    Unmounts the dmg at mountpoint
    """
    proc = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint],
                                bufsize=1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    (unused_output, err) = proc.communicate()
    if proc.returncode:
        display_warning('Polite unmount failed: %s' % err)
        display_info('Attempting to force unmount %s' % mountpoint)
        # try forcing the unmount
        retcode = subprocess.call(['/usr/bin/hdiutil', 'detach', mountpoint,
                                '-force'])
        if retcode:
            display_warning('Failed to unmount %s' % mountpoint)


def gethash(filename, hash_function):
    """
    Calculates the hashvalue of the given file with the given hash_function.

    Args:
      filename: The file name to calculate the hash value of.
      hash_function: The hash function object to use, which was instanciated
          before calling this function, e.g. hashlib.md5().

    Returns:
      The hashvalue of the given file as hex string.
    """
    if not os.path.isfile(filename):
        return 'NOT A FILE'

    f = open(filename, 'rb')
    while 1:
        chunk = f.read(2**16)
        if not chunk:
            break
        hash_function.update(chunk)
    f.close()
    return hash_function.hexdigest()


def getmd5hash(filename):
    """
    Returns hex of MD5 checksum of a file
    """
    hash_function = hashlib.md5()
    return gethash(filename, hash_function)


def getsha256hash(filename):
    """
    Returns the SHA-256 hash value of a file as a hex string.
    """
    hash_function = hashlib.sha256()
    return gethash(filename, hash_function)


def isApplication(pathname):
    """Returns true if path appears to be an OS X application"""
    # No symlinks, please
    if os.path.islink(pathname):
        return False
    if pathname.endswith('.app'):
        return True
    if os.path.isdir(pathname):
        # look for app bundle structure
        # use Info.plist to determine the name of the executable
        infoplist = os.path.join(pathname, 'Contents', 'Info.plist')
        if os.path.exists(infoplist):
            plist = FoundationPlist.readPlist(infoplist)
            if 'CFBundlePackageType' in plist:
                if plist['CFBundlePackageType'] != 'APPL':
                    return False
            # get CFBundleExecutable,
            # falling back to bundle name if it's missing
            bundleexecutable = plist.get('CFBundleExecutable',
                                      os.path.basename(pathname))
            bundleexecutablepath = os.path.join(pathname, 'Contents',
                                                'MacOS', bundleexecutable)
            if os.path.exists(bundleexecutablepath):
                return True
    return False


#####################################################
# managed installs preferences/metadata
#####################################################


def prefs(force_refresh=False):
    """Loads and caches preferences from ManagedInstalls.plist.

    Args:
      force_refresh: Boolean. If True, wipe prefs and reload from scratch. If
          False (default), load from cache if it's already set.

    Returns:
      Dict of preferences.
    """
    global _prefs
    if not _prefs or force_refresh:
        _prefs = {}  # start with a clean state.
        _prefs['ManagedInstallDir'] = '/Library/Managed Installs'
        # convenience; to be replaced with CatalogURL and PackageURL
        _prefs['SoftwareRepoURL'] = 'http://munki/repo'
        # effective defaults for the following three; though if they
        # are not in the prefs plist, they are calculated relative
        # to the SoftwareRepoURL (if it exists)
        #prefs['ManifestURL'] = 'http://munki/repo/manifests/'
        #prefs['CatalogURL'] = 'http://munki/repo/catalogs/'
        #prefs['PackageURL'] = 'http://munki/repo/pkgs/'
        _prefs['ClientIdentifier'] = ''
        _prefs['LogFile'] = \
            '/Library/Managed Installs/Logs/ManagedSoftwareUpdate.log'
        _prefs['LoggingLevel'] = 1
        _prefs['InstallAppleSoftwareUpdates'] = False
        _prefs['SoftwareUpdateServerURL'] = ''
        _prefs['DaysBetweenNotifications'] = 1
        _prefs['LastNotifiedDate'] = '1970-01-01 00:00:00 -0000'
        _prefs['UseClientCertificate'] = False
        _prefs['SuppressUserNotification'] = False
        _prefs['SuppressAutoInstall'] = False
        _prefs['SuppressStopButtonOnInstall'] = False
        _prefs['PackageVerificationMode'] = 'hash'

        # Load configs from ManagedInstalls.plist file
        if not loadPrefsFromFile(_prefs, MANAGED_INSTALLS_PLIST_PATH):
            # no prefs file, so we'll write out a 'default' prefs file
            del _prefs['LastNotifiedDate']
            FoundationPlist.writePlist(_prefs, prefsfile)

        # Load configs from SecureConfig.plist file; overwrite existing configs
        secure_config_file_path = os.path.join(
            _prefs['ManagedInstallDir'], SECURE_CONFIG_PLIST_REL_PATH)
        if loadPrefsFromFile(_prefs, secure_config_file_path):
          _prefs['SecureConfigFile'] = secure_config_file_path

    return _prefs


def loadPrefsFromFile(prefs, filepath):
    """Loads preferences from a file into the passed prefs dictionary.

    Args:
      prefs: dictionary of configurations to update.
      filepath: str path of file to read configurations from.
    Returns:
      Boolean. True if the file exists and prefs was updated, False otherwise.
    Raises:
      Error: there was an error reading the specified preferences file.
    """
    if not os.path.exists(filepath):
        return False

    plist = {}
    try:
        plist = FoundationPlist.readPlist(filepath)
    except FoundationPlist.NSPropertyListSerializationException:
        display_error('ERROR: Could not read preferences file %s.' % filepath)
        raise PreferencesError(
            'Could not read preferences file %s.' % filepath)
    try:
        for key in plist.keys():
            if type(plist[key]).__name__ == '__NSCFDate':
                # convert NSDate/CFDates to strings
                _prefs[key] = str(plist[key])
            else:
                _prefs[key] = plist[key]
    except AttributeError:
        display_error('ERROR: Prefs file %s contains invalid data.' % filepath)
        raise PreferencesError('Preferences file %s invalid.' % filepath)
    return True


def pref(prefname):
    """Return a prefernce"""
    return prefs().get(prefname,'')


#####################################################
# Apple package utilities
#####################################################

def getInstallerPkgInfo(filename):
    """Uses Apple's installer tool to get basic info
    about an installer item."""
    installerinfo = {}
    proc = subprocess.Popen(['/usr/sbin/installer', '-pkginfo', '-verbose',
                             '-plist', '-pkg', filename],
                             bufsize=1, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    (out, unused_err) = proc.communicate()

    if out:
        # discard any lines at the beginning that aren't part of the plist
        lines = str(out).splitlines()
        plist = ''
        for index in range(len(lines)):
            try:
                plist = FoundationPlist.readPlistFromString(
                                                '\n'.join(lines[index:]) )
            except FoundationPlist.NSPropertyListSerializationException:
                pass
            if plist:
                break
        if plist:
            if 'Size' in plist:
                installerinfo['installed_size'] = int(plist['Size'])
            installerinfo['description'] = plist.get('Description', '')
            if plist.get('Will Restart') == 'YES':
                installerinfo['RestartAction'] = 'RequireRestart'
            if 'Title' in plist:
                installerinfo['display_name'] = plist['Title']

    proc = subprocess.Popen(['/usr/sbin/installer',
                            '-query', 'RestartAction',
                            '-pkg', filename],
                            bufsize=1,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (out, unused_err) = proc.communicate()
    if out:
        restartAction = str(out).rstrip('\n')
        if restartAction != 'None':
            installerinfo['RestartAction'] = restartAction

    return installerinfo


def padVersionString(versString, tupleCount):
    """Normalize the format of a version string"""
    if versString == None:
        versString = '0'
    components = str(versString).split('.')
    if len(components) > tupleCount :
        components = components[0:tupleCount]
    else:
        while len(components) < tupleCount :
            components.append('0')
    return '.'.join(components)


def getVersionString(plist):
    """Gets a version string from the plist.
    If there's a valid CFBundleShortVersionString, returns that.
    else if there's a CFBundleVersion, returns that
    else returns an empty string."""
    CFBundleShortVersionString = ''
    if plist.get('CFBundleShortVersionString'):
        CFBundleShortVersionString = \
            plist['CFBundleShortVersionString'].split()[0]
    if 'Bundle versions string, short' in plist:
        CFBundleShortVersionString = \
            plist['Bundle versions string, short'].split()[0]
    if CFBundleShortVersionString:
        if CFBundleShortVersionString[0] in '0123456789':
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            CFBundleShortVersionString = \
                CFBundleShortVersionString.replace(',','.')
            return CFBundleShortVersionString
    if plist.get('CFBundleVersion'):
        # no CFBundleShortVersionString, or bad one
        CFBundleVersion = str(plist['CFBundleVersion']).split()[0]
        if CFBundleVersion[0] in '0123456789':
            # starts with a number; that's good
            # now for another edge case thanks to Adobe:
            # replace commas with periods
            CFBundleVersion = CFBundleVersion.replace(',','.')
            return CFBundleVersion

    return ''


def getExtendedVersion(bundlepath):
    """
    Returns five-part version number like Apple uses in distribution
    and flat packages
    """
    infoPlist = os.path.join(bundlepath, 'Contents', 'Info.plist')
    if os.path.exists(infoPlist):
        plist = FoundationPlist.readPlist(infoPlist)
        versionstring = getVersionString(plist)
        if versionstring:
            return padVersionString(versionstring, 5)

    # no version number in Info.plist. Maybe old-style package?
    infopath = os.path.join(bundlepath, 'Contents', 'Resources',
                                'English.lproj')
    if os.path.exists(infopath):
        for item in os.listdir(infopath):
            if os.path.join(infopath, item).endswith('.info'):
                infofile = os.path.join(infopath, item)
                fileobj = open(infofile, mode='r')
                info = fileobj.read()
                fileobj.close()
                infolines = info.splitlines()
                for line in infolines:
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        label = parts[0]
                        if label == 'Version':
                            return padVersionString(parts[1], 5)

    # didn't find a version number, so return 0...
    return '0.0.0.0.0'


def parsePkgRefs(filename):
    """Parses a .dist or PackageInfo file looking for pkg-ref or pkg-info tags
    to get info on included sub-packages"""
    info = []
    dom = minidom.parse(filename)
    pkgrefs = dom.getElementsByTagName('pkg-ref')
    if pkgrefs:
        for ref in pkgrefs:
            keys = ref.attributes.keys()
            if 'id' in keys and 'version' in keys:
                pkginfo = {}
                pkginfo['packageid'] = \
                             ref.attributes['id'].value.encode('UTF-8')
                pkginfo['version'] = padVersionString(
                           ref.attributes['version'].value.encode('UTF-8'), 5)
                if 'installKBytes' in keys:
                    pkginfo['installed_size'] = int(
                        ref.attributes['installKBytes'].value.encode('UTF-8'))
                if not pkginfo['packageid'].startswith('manual'):
                    if not pkginfo in info:
                        info.append(pkginfo)
    else:
        pkgrefs = dom.getElementsByTagName('pkg-info')
        if pkgrefs:
            for ref in pkgrefs:
                keys = ref.attributes.keys()
                if 'identifier' in keys and 'version' in keys:
                    pkginfo = {}
                    pkginfo['packageid'] = \
                           ref.attributes['identifier'].value.encode('UTF-8')
                    pkginfo['version'] = \
                           padVersionString(
                            ref.attributes['version'].value.encode('UTF-8'),5)
                    payloads = ref.getElementsByTagName('payload')
                    if payloads:
                        keys = payloads[0].attributes.keys()
                        if 'installKBytes' in keys:
                            pkginfo['installed_size'] = int(
                                payloads[0].attributes[
                                    'installKBytes'].value.encode('UTF-8'))
                    if not pkginfo in info:
                        info.append(pkginfo)
    return info


def getFlatPackageInfo(pkgpath):
    """
    returns array of dictionaries with info on subpackages
    contained in the flat package
    """

    infoarray = []
    # get the absolute path to the pkg because we need to do a chdir later
    abspkgpath = os.path.abspath(pkgpath)
    # make a tmp dir to expand the flat package into
    pkgtmp = tempfile.mkdtemp(dir=tmpdir)
    # record our current working dir
    cwd = os.getcwd()
    # change into our tmpdir so we can use xar to unarchive the flat package
    os.chdir(pkgtmp)
    returncode = subprocess.call(['/usr/bin/xar', '-xf', abspkgpath,
                                  '--exclude', 'Payload'])
    if returncode == 0:
        currentdir = pkgtmp
        packageinfofile = os.path.join(currentdir, 'PackageInfo')
        if os.path.exists(packageinfofile):
            infoarray = parsePkgRefs(packageinfofile)

        if not infoarray:
            # didn't get any packageid info or no PackageInfo file
            # look for subpackages at the top level
            for item in os.listdir(currentdir):
                itempath = os.path.join(currentdir, item)
                if itempath.endswith('.pkg') and os.path.isdir(itempath):
                    packageinfofile = os.path.join(itempath, 'PackageInfo')
                    if os.path.exists(packageinfofile):
                        infoarray.extend(parsePkgRefs(packageinfofile))

        if not infoarray:
            # found no PackageInfo files and no subpackages,
            # so let's look at the Distribution file
            distributionfile = os.path.join(currentdir, 'Distribution')
            if os.path.exists(distributionfile):
                infoarray = parsePkgRefs(distributionfile)

    # change back to original working dir
    os.chdir(cwd)
    shutil.rmtree(pkgtmp)
    return infoarray


def getOnePackageInfo(pkgpath):
    """Gets receipt info for a single bundle-style package"""
    pkginfo = {}
    plistpath = os.path.join(pkgpath, 'Contents', 'Info.plist')
    if os.path.exists(plistpath):
        pkginfo['filename'] = os.path.basename(pkgpath)
        try:
            plist = FoundationPlist.readPlist(plistpath)
            if 'CFBundleIdentifier' in plist:
                pkginfo['packageid'] = plist['CFBundleIdentifier']
            elif 'Bundle identifier' in plist:
                # special case for JAMF Composer generated packages.
                pkginfo['packageid'] = plist['Bundle identifier']
            else:
                pkginfo['packageid'] = os.path.basename(pkgpath)

            if 'CFBundleName' in plist:
                pkginfo['name'] = plist['CFBundleName']

            if 'IFPkgFlagInstalledSize' in plist:
                pkginfo['installed_size'] = plist['IFPkgFlagInstalledSize']

            pkginfo['version'] = getExtendedVersion(pkgpath)
        except (AttributeError,
                FoundationPlist.NSPropertyListSerializationException):
            pkginfo['packageid'] = 'BAD PLIST in %s' % \
                                    os.path.basename(pkgpath)
            pkginfo['version'] = '0.0.0.0.0'
    else:
        # look for old-style .info files!
        infopath = os.path.join(pkgpath, 'Contents', 'Resources',
                                    'English.lproj')
        if os.path.exists(infopath):
            for item in os.listdir(infopath):
                if os.path.join(infopath, item).endswith('.info'):
                    pkginfo['filename'] = os.path.basename(pkgpath)
                    pkginfo['packageid'] = os.path.basename(pkgpath)
                    infofile = os.path.join(infopath, item)
                    fileobj = open(infofile, mode='r')
                    info = fileobj.read()
                    fileobj.close()
                    infolines = info.splitlines()
                    for line in infolines:
                        parts = line.split(None, 1)
                        if len(parts) == 2:
                            label = parts[0]
                            if label == 'Version':
                                pkginfo['version'] = \
                                    padVersionString(parts[1], 5)
                            if label == 'Title':
                                pkginfo['name'] = parts[1]
                    break
    return pkginfo


def getText(nodelist):
    """Helper function to get text from XML child nodes"""
    text = ""
    for node in nodelist:
        if node.nodeType == node.TEXT_NODE:
            text = text + node.data
    return text


def getBundlePackageInfo(pkgpath):
    """Get metadata from a bundle-style package"""
    infoarray = []

    if pkgpath.endswith('.pkg'):
        pkginfo = getOnePackageInfo(pkgpath)
        if pkginfo:
            infoarray.append(pkginfo)
            return infoarray

    bundlecontents = os.path.join(pkgpath, 'Contents')
    if os.path.exists(bundlecontents):
        for item in os.listdir(bundlecontents):
            if item.endswith('.dist'):
                filename = os.path.join(bundlecontents, item)
                dom = minidom.parse(filename)
                pkgrefs = dom.getElementsByTagName('pkg-ref')
                if pkgrefs:
                    # try to find subpackages from the file: references
                    for ref in pkgrefs:
                        fileref = getText(ref.childNodes)
                        if fileref.startswith('file:'):
                            relativepath = urllib2.unquote(fileref[5:])
                            subpkgpath = os.path.join(pkgpath, relativepath)
                            if os.path.exists(subpkgpath):
                                pkginfo = getBundlePackageInfo(subpkgpath)
                                if pkginfo:
                                    infoarray.extend(pkginfo)

                    if infoarray:
                        return infoarray

        # no .dist file found, look for packages in subdirs
        dirsToSearch = []
        plistpath = os.path.join(pkgpath, 'Contents', 'Info.plist')
        if os.path.exists(plistpath):
            plist = FoundationPlist.readPlist(plistpath)
            if 'IFPkgFlagComponentDirectory' in plist:
                componentdir = plist['IFPkgFlagComponentDirectory']
                dirsToSearch.append(componentdir)

        if dirsToSearch == []:
            dirsToSearch = ['', 'Contents', 'Contents/Installers',
                            'Contents/Packages', 'Contents/Resources',
                            'Contents/Resources/Packages']
        for subdir in dirsToSearch:
            searchdir = os.path.join(pkgpath, subdir)
            if os.path.exists(searchdir):
                for item in os.listdir(searchdir):
                    itempath = os.path.join(searchdir, item)
                    if os.path.isdir(itempath):
                        if itempath.endswith('.pkg'):
                            pkginfo = getOnePackageInfo(itempath)
                            if pkginfo:
                                infoarray.append(pkginfo)
                        elif itempath.endswith('.mpkg'):
                            pkginfo = getBundlePackageInfo(itempath)
                            if pkginfo:
                                infoarray.extend(pkginfo)

        if infoarray:
            return infoarray
        else:
            # couldn't find any subpackages,
            # just return info from the .dist file
            # if it exists
            for item in os.listdir(bundlecontents):
                if item.endswith('.dist'):
                    distfile = os.path.join(bundlecontents, item)
                    infoarray.extend(parsePkgRefs(distfile))

    return infoarray


def getReceiptInfo(pkgname):
    """Get receipt info from a package"""
    info = []
    if pkgname.endswith('.pkg') or pkgname.endswith('.mpkg'):
        display_debug2('Examining %s' % pkgname)
        if os.path.isfile(pkgname):       # new flat package
            info = getFlatPackageInfo(pkgname)

        if os.path.isdir(pkgname):        # bundle-style package?
            info = getBundlePackageInfo(pkgname)

    elif pkgname.endswith('.dist'):
        info = parsePkgRefs(pkgname)

    return info


def getInstalledPackageVersion(pkgid):
    """
    Checks a package id against the receipts to
    determine if a package is already installed.
    Returns the version string of the installed pkg
    if it exists, or an empty string if it does not
    """

    # First check (Leopard and later) package database

    proc = subprocess.Popen(['/usr/sbin/pkgutil',
                             '--pkg-info-plist', pkgid],
                             bufsize=1,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    (out, unused_err) = proc.communicate()

    if out:
        try:
            plist = FoundationPlist.readPlistFromString(out)
        except FoundationPlist.NSPropertyListSerializationException:
            pass
        else:
            foundbundleid = plist.get('pkgid')
            foundvers = plist.get('pkg-version', '0.0.0.0.0')
            if pkgid == foundbundleid:
                display_debug2('\tThis machine has %s, version %s' %
                                (pkgid, foundvers))
            return padVersionString(foundvers, 5)

    # If we got to this point, we haven't found the pkgid yet.
    # Check /Library/Receipts
    receiptsdir = '/Library/Receipts'
    if os.path.exists(receiptsdir):
        installitems = os.listdir(receiptsdir)
        highestversion = '0'
        for item in installitems:
            if item.endswith('.pkg'):
                info = getBundlePackageInfo(os.path.join(receiptsdir, item))
                if len(info):
                    infoitem = info[0]
                    foundbundleid = infoitem['packageid']
                    foundvers = infoitem['version']
                    if pkgid == foundbundleid:
                        if version.LooseVersion(foundvers) > \
                           version.LooseVersion(highestversion):
                            highestversion = foundvers

        if highestversion != '0':
            display_debug2('\tThis machine has %s, version %s' %
                            (pkgid, highestversion))
            return highestversion


    # This package does not appear to be currently installed
    display_debug2('\tThis machine does not have %s' % pkgid)
    return ""


def nameAndVersion(aString):
    """
    Splits a string into the name and version numbers:
    'TextWrangler2.3b1' becomes ('TextWrangler', '2.3b1')
    'AdobePhotoshopCS3-11.2.1' becomes ('AdobePhotoshopCS3', '11.2.1')
    'MicrosoftOffice2008v12.2.1' becomes ('MicrosoftOffice2008', '12.2.1')
    """
    index = 0
    for char in aString:
        if char in '0123456789':
            possibleVersion = aString[index:]
            if not (' ' in possibleVersion or '_' in possibleVersion or \
                    '-' in possibleVersion or 'v' in possibleVersion):
                return (aString[0:index].rstrip(' .-_v'), possibleVersion)
        index += 1
    # no version number found, just return original string and empty string
    return (aString, '')


def findInstallerItem(path):
    """Find an installer item in the directory given by path"""
    if path.endswith('.pkg') or path.endswith('.mpkg') or \
       path.endswith('.dmg'):
        return path
    else:
        # Apple Software Updates download as directories
        # with .dist files and .pkgs
        if os.path.exists(path) and os.path.isdir(path):
            for item in os.listdir(path):
                if item.endswith('.pkg'):
                    return path

            # we didn't find a pkg at this level
            # look for a Packages dir
            path = os.path.join(path,'Packages')
            if os.path.exists(path) and os.path.isdir(path):
                for item in os.listdir(path):
                    if item.endswith('.pkg'):
                        return path
    # found nothing!
    return ''


def getPackageMetaData(pkgitem):
    """
    Queries an installer item (.pkg, .mpkg, .dist)
    and gets metadata. There are a lot of valid Apple package formats
    and this function may not deal with them all equally well.
    Standard bundle packages are probably the best understood and documented,
    so this code deals with those pretty well.

    metadata items include:
    installer_item_size:  size of the installer item (.dmg, .pkg, etc)
    installed_size: size of items that will be installed
    RestartAction: will a restart be needed after installation?
    name
    version
    description
    receipts: an array of packageids that may be installed
              (some may not be installed on some machines)
    """

    pkgitem = findInstallerItem(pkgitem)
    if pkgitem == None:
        return {}

    # first get the data /usr/sbin/installer will give us
    installerinfo = getInstallerPkgInfo(pkgitem)
    # now look for receipt/subpkg info
    receiptinfo = getReceiptInfo(pkgitem)

    name = os.path.split(pkgitem)[1]
    shortname = os.path.splitext(name)[0]
    metaversion = getExtendedVersion(pkgitem)
    if metaversion == '0.0.0.0.0':
        metaversion = nameAndVersion(shortname)[1]

    highestpkgversion = '0.0'
    installedsize = 0
    for infoitem in receiptinfo:
        if version.LooseVersion(infoitem['version']) > \
           version.LooseVersion(highestpkgversion):
            highestpkgversion = infoitem['version']
            if 'installed_size' in infoitem:
                # note this is in KBytes
                installedsize += infoitem['installed_size']

    if metaversion == '0.0.0.0.0':
        metaversion = highestpkgversion
    elif len(receiptinfo) == 1:
        # there is only one package in this item
        metaversion = highestpkgversion
    elif highestpkgversion.startswith(metaversion):
        # for example, highestpkgversion is 2.0.3124.0,
        # version in filename is 2.0
        metaversion = highestpkgversion

    cataloginfo = {}
    cataloginfo['name'] = nameAndVersion(shortname)[0]
    cataloginfo['version'] = metaversion
    for key in ('display_name', 'RestartAction', 'description'):
        if key in installerinfo:
            cataloginfo[key] = installerinfo[key]

    if 'installed_size' in installerinfo:
        if installerinfo['installed_size'] > 0:
            cataloginfo['installed_size'] = installerinfo['installed_size']
    elif installedsize:
        cataloginfo['installed_size'] = installedsize

    cataloginfo['receipts'] = receiptinfo

    return cataloginfo


# some utility functions


def verifyFileOnlyWritableByMunkiAndRoot(file_path):
    """
    Check the permissions on a given file path; fail if owner or group
    does not match the munki process (default: root/admin) or the group is not
    'wheel', or if other users are able to write to the file. This prevents
    escalated execution of arbitrary code.

    Args:
      file_path: str path of file to verify permissions on.
    Raises:
      VerifyFilePermissionsError: there was an error verifying file permissions.
      InsecureFilePermissionsError: file permissions were found to be insecure.
    """
    try:
        file_stat = os.stat(file_path)
    except OSError, e:
        raise VerifyFilePermissionsError(
            '%s does not exist. \n %s' % (file_path, str(e)))

    try:
        # verify the munki process uid matches the file owner uid.
        if os.geteuid() != file_stat.st_uid:
            raise InsecureFilePermissionsError(
                'owner does not match munki process!')
        # verify the munki process gid matches the file owner gid, or the file
        # owner gid is 80 (which is the admin group root is a member of).
        elif os.getegid() != file_stat.st_gid and file_stat.st_gid != 80:
            raise InsecureFilePermissionsError(
                'group does not match munki process!')
        # verify other users cannot write to the file.
        elif file_stat.st_mode & stat.S_IWOTH != 0:
            raise InsecureFilePermissionsError('world writable!')
    except InsecureFilePermissionsError, e:
        raise InsecureFilePermissionsError(
            '%s is not secure! %s' % (file_path, e.args[0]))


def getAvailableDiskSpace(volumepath='/'):
    """Returns available diskspace in KBytes."""
    cmd = ['/usr/sbin/diskutil', 'info', '-plist', volumepath]
    proc = subprocess.Popen(cmd,
                            bufsize=1,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (out, unused_err) = proc.communicate()
    if out:
        try:
            plist = FoundationPlist.readPlistFromString(out)

            if 'FreeSpace' in plist:
                # plist['FreeSpace'] is in bytes
                return int(plist['FreeSpace']/1024)

        except (AttributeError,
                FoundationPlist.NSPropertyListSerializationException):
            pass

    # Yikes
    return 0


def cleanUpTmpDir():
    """Cleans up our temporary directory."""
    global tmpdir
    if tmpdir:
        try:
            shutil.rmtree(tmpdir)
        except (OSError, IOError):
            pass
        tmpdir = None


# module globals
#debug = False
verbose = 1
munkistatusoutput = False
tmpdir = tempfile.mkdtemp()
_prefs = {}  # never access this directly; use prefs() instead.
report = {}
report['Errors'] = []
report['Warnings'] = []


def main():
    """Placeholder"""
    print 'This is a library of support tools for the Munki Suite.'

if __name__ == '__main__':
    main()

