#!/usr/bin/env python





if __name__ == "__main__":
    
    # setup our path so we can load our custom modules
    from sys import path
    path.append('/home/brian/porthole')
    from sys import argv, exit, stderr
    from getopt import getopt, GetoptError

import re,string
from utils import dprint
from string import zfill
import portagelib, utils

############### new code ###############

ver_regexp = re.compile("^(cvs-)?(\\d+)((\\.\\d+)*)([a-zA-Z]?)((_(pre|p|beta|alpha|rc)\\d*)*)(-r(\\d+))?$")
suffix_regexp = re.compile("^(alpha|beta|rc|pre|p)(\\d*)$")
# modified portage comparison suffix values for sorting in desired precedence
suffix_value = {"alpha": '0', "beta": '1', "pre": '2', "rc": '3', "p": '4'}

# most version numbers will not exceed 2 digits, but make it 3 just in case
fill_size = 3

def pad_ver(vlist):
    """pads the version string so all number sequences are the same
       length for acurate sorting, borrowed & modified code from new portage vercmp()"""
    dprint("pad_ver: pad_ver()  vlist[]")
    #dprint(vlist)
    # short circuit for  list of 1
    if len(vlist) == 1:
        return vlist

    max_length = 0

    suffix_count = 0
    # suffix length may have dates for version number (8) so make it 2 extra just in case
    suffix_length = 10
    # the lack of a suffix would imply the largest value possible for it
    suffix_pad = "0"

    val_cache = []

    dprint("VERSION_SORT: pad_ver() checking maximum length value of version pattern") 
    for x in vlist:
        #dprint(x)
        max_length = max(max_length, string.count(x, '.'))
        suffix_count = max(suffix_count, string.count(x, "_"))

    dprint("max_length = %d, suffix_count =%d" \
           %(max_length, suffix_count))

    for val1 in vlist:
        #dprint("new val1 = %s" %val1)
        match1 = ver_regexp.match(val1)
        # checking that the versions are valid
        if not match1 or not match1.groups():
            dprint("!!! syntax error in version:")
            dprint(val1)
            return None

	# building lists of the version parts before the suffix
	# first part is simple
        list1 = [zfill(match1.group(2), fill_size)]

	# extend version numbers
        # this part would greatly benefit from a fixed-length version pattern
        if len(match1.group(3)):
            vlist1 = match1.group(3)[1:].split(".")
            for i in range(0, max_length):
                if len(vlist1) <= i or len(vlist1[i]) == 0:
                    list1.append(zfill("0",fill_size))
                else:
                    list1.append(zfill(vlist1[i],fill_size))

        # and now the final letter
        #dprint("final letter")
        if len(match1.group(5)):
            list1.append(match1.group(5))
        else: # add something to it in case there is a letter in a vlist member
            list1.append("!") # "!" is the first visible printable char

        # main version is done, so now the _suffix part
        #dprint("suffix part")
        list1b = match1.group(6).split("_")[1:]

        for i in range(0, suffix_count):
            s1 = None
            if len(list1b) <= i:
                s1 = str(suffix_value["p"]) + zfill(suffix_pad, suffix_length)
            else:
                slist = suffix_regexp.match(list1b[i]).groups()
                s1 = str(suffix_value[slist[0]]) + zfill(slist[1], suffix_length)
            if s1:
                #dprint("s1")
                #dprint(s1)
                list1 += [s1]
                
        # the suffix part is done, so finally the revision
        #dprint("revision part")
        r1 = None	
        if match1.group(10):
            r1 = 'r' + zfill(match1.group(10), fill_size)
        else:
            r1 ='r' + zfill("0", fill_size)
        if r1:
            list1 += [r1]

        # reconnect the padded version string
        result = ''
        for y in list1:
            result += y
        #dprint("result= %s" %result)

        # store the padded version
        val_cache += [result]

    #dprint(val_cache)
    dprint("VERSION_SORT: pad_ver() done")
    return val_cache

def two_list_sort(keylist, versions):
    """sorts the versions list using the keylist values"""
    dprint("two_list_sort() keylist, versions")
    #dprint(keylist)
    #dprint(versions)
    dbl_list = {}
    for x in range(0,len(versions)):
        dbl_list[keylist[x]] =  versions[x]

    # Sort the versions using the padded keylist
    keylist.sort()

    #rebuild versions in sorted order
    result = []
    for key in keylist:
        result += [dbl_list[key]]
    return result

def ver_sort(versions):
    """sorts a version list according to portage versioning rules"""
    dprint("VERSION_SORT: ver_sort()")
    # convert versions into the padded version only list
    vlist = []
    for v in versions:
        #dprint(v)
        vlist += [portagelib.get_version(v)]
        #dprint(vlist)
    keylist = pad_ver(vlist)
    if not keylist: # there was an error
        dprint("keylist[] creation error")
        return (versions + ["error_in_sort"]) 
    sorted = two_list_sort(keylist, versions)
    #dprint("VERSION_SORT: ver_sort() complete!")
    return sorted

if __name__ == "__main__":


    utils.debug = True

    versions = ['net-mail/some_package-1.1','net-mail/some_package-1.0',
                'net-mail/some_package-1.21','net-mail/some_package-1.21.1',
                'net-mail/some_package-1.1-r1','net-mail/some_package-1.0_pre1',
                'net-mail/some_package-1.3.1_rc2','net-mail/some_package-1.1a',
                'net-mail/some_package-1.23.4_pre2','net-mail/some_package-1.3.1_p1',
                'net-mail/some_package-1.1a-r2','net-mail/some_package-1.21.2'
                ]

    sorted = ver_sort(versions)
    dprint("new sorted version list")
    dprint(sorted)



    
