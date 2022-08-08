#!/usr/bin/python3
"""post1.py
Langmuir probe post-processing module: step 1.

This file doubles as an executable command-line utility for performing
the first post-processing step and as an importable module that exposes
the post1() function as a utility for other scripts.

Raw data collected from the Langmuir probe are wire current and a 
digital photo-reflector signal recorded at regular samples in time. The
post1() function transposes these into four groups of 
"""

import os,sys,shutil
import argparse
import lconfig as lc
import numpy as np
import pickle
import multiprocessing as mp


target = 'post1'
extension = '.p1d'


def post1(source, target=None, Nwire=4, theta_min=-0.3, theta_max=0.3, quiet=False):
    """Accepts a path to the .dat file to load and a .p1d file to generate
    out = post1(source, target=None)
    
The source should be a path to a .dat file containing the original wire
data.  The target should be a .p1d file to which the post-processing 
results will be written.  If target is set to any value that evaluates 
to a boolean False (like "" or None), no results will be written.

The post1 function returns the same output dictionary that is written to
the target file.  It is an array of dicts with a "theta" and a "current"
entry.  They are lists of angles and current measurements respectively,
and each dict corresponds to one of the wires.

The digital signal is used to establish on which sample wire 1 (index 0)
passes through 0 degrees.  All samples between these events are 
interpolated to establish the disc angle.  Since each of the wires are 
precisely placed equidistant around the disc, the sample where each 
wire passes through 0 degrees can also be stablished.
"""
    if not quiet:
        print('[' + source + '] starting...')
        
    conf,data = lc.load(source)

    # Detect the digital input channel
    dich = int(np.log2(conf.distream))

    # First, establish the edge events
    edges_I = data.get_dievents(dich)
    # Get the current signal
    current = data.get_channel(0)
    Ndata = data.ndata()
    
    # The digital signal is nominally high over most of the rotation.
    # It drops when a stripe of dark tape passes under the 
    # photoreflector.  There are two pieces of tape - each of a 
    # different width.  The widest one has one edge carefully aligned 
    # the axis of wire 1.  The narrower piece of tape is placed a small
    # distance from the edge aligned with wire one.  In this way, it is
    # possible to determine which side of the wider pulse should be used
    # to identify 0 degrees.
    
    # Measure out the durations of the first four intervals (5 edges)
    # The longest interval will correspond to the disc transit
    edges_dI = edges_I[1:5] - edges_I[0:4]
    ii = np.argmax(edges_dI)  # longest interval
    # If the first pulse is the longest of the two
    if edges_dI[(ii+1)%4] > edges_dI[(ii+3)%4]:
        ii = (ii+2)%4
    # If the first pulse is the shorter of the two
    else:
        ii = (ii+3)%4
        
    # Now, starting at ii, downselect all the edges
    edges_I = edges_I[ii::4]
    # Calculate the samples between complete rotations.
    edges_dI = np.empty_like(edges_I,dtype=int)
    edges_dI[:-1] = np.diff(edges_I)
    edges_dI[-1] = edges_dI[-2]
    # If there is greater than 1% variation, there is a problem.
    if np.max(edges_dI)/np.min(edges_dI) > 1.01:
        raise Exception('The disc speed varied by more than 1% in file: ' + source)

    # edges_I is now an array of every index corresponding to 0rad of 
    # disc rotation.
    # edges_dI is an array of indices with the number of samples between
    # edges (for a single rotation).  The last element has been 
    # duplicated so it is the same length as edges_I.
    
    # Initialize a result - we'll write it with json
    out = {
        'xi':conf.get_meta('xi'),
        'xn':conf.get_meta('xn'),
        'xstep':conf.get_meta('xstep'),
        'zi':conf.get_meta('zi'),
        'zn':conf.get_meta('zn'),
        'zstep':conf.get_meta('zstep'),
    }
    out['wire'] = [{'theta':[], 'current':[]} for ii in range(Nwire)]
    wire = out['wire']
    
    # First, look for pedestals that happened before the first wire 1 
    # trigger event.  We'll be using the first edge pair to extrapolate.
    I = edges_I[0]
    dI = edges_dI[0]
    # Calculate the angle rotated between each sample
    dtheta = 2*np.pi / dI
    # Loop through wire indices
    for iwire in range(Nwire):
        Izero = I - ((Nwire-iwire)*dI) // Nwire
        Imin = max(0, Izero + int(theta_min / dtheta))
        Imax = max(0, Izero + int(theta_max / dtheta))
        # use ii for an iterator over individual indices
        for ii in range( Imin, Imax ):
            wire[iwire]['theta'].append((ii - Izero) * dtheta)
            wire[iwire]['current'].append(current[ii])
    
    # Next, loop through the other rotations
    for I, dI, in zip(edges_I, edges_dI):
        # Calculate the angle rotated between each sample
        dtheta = 2*np.pi / dI
        # Loop through wire indices
        for iwire in range(Nwire):
            Izero = I + (iwire*dI) // Nwire
            Imin = min(Ndata-1, Izero + int(theta_min / dtheta))
            Imax = min(Ndata-1, Izero + int(theta_max / dtheta))
            # use ii for an iterator over individual indices
            for ii in range( Imin, Imax ):
                wire[iwire]['theta'].append((ii - Izero) * dtheta)
                wire[iwire]['current'].append(current[ii])

    if target:
        if not quiet:
            print('[' + source + '] writing: ' + target)
        with open(target, 'wb') as ff:
            pickle.dump(out, ff)

    if not quiet:
        print('[' + source + '] done.')
    return out


# If this is being run as a script
if __name__ == '__main__':
    
    # Set up argument parsing
    parser = argparse.ArgumentParser(
            prog='ion_exp12/bin/post1.py',
            description='Langmuir probe post processing step 1',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=\
"""The source directory is expected to contain a series of *.dat files with
raw data collected from the Langmuir probe are wire current and a 
digital photo-reflector signal.  The first post processing step 
translates these from a time series of current measurements into current
versus disc angle.

Since data directories are usually long timestamps, post1 also allows
the source to be specified by the trailing characters of the source when
the -d option is also set to a parent directory in which to look.
This example will look in the directory, ../data for a data directory
that ends in the digits 3715:
    $ post1.py -d ../data 3715
If multiple matches are found, an error is raised.

Source data files must have a ".dat" extension, and they must be lconfig
data with an analog input and a digital input stream channel.  Files 
beginning with a an underscore (_) are ignored, which allows files to be
excluded from analysis without their deletion.

The output is written to a "post1" directory inside the source 
directory.  If that directory is found to already exist, the operation
is aborted with an error unless the -f (--force) flag is set.

Output are python pickle dumps of a dicts containing the xi, xn, xstep,
zi, zn, and zstep from each file.  The measurement results are in a 
'wire' member list of dicts containing 'theta' (in radians) and 
'current' (in uA) lists.

Experiment 12 permits multiple wires to be mounted on a single disc, so 
the output is organized by wire, and the angles reported are measured 
between each wire and the x-axis (axis of motion into the flame).  This
is done using the photoreflector to determine the instances at which 
wire 1 is at zero radians.  Then, the location of the disc is inferred 
by interpolation.  The wires are presumed to be equally spaced around 
the disc.
""")
    parser.add_argument('source',
            help='The data source directory to target',
            default=None)
            
    parser.add_argument('-f', '--force', 
            dest='force',
            help='Force overwriting prior post1 results',
            action='store_true')
            
    parser.add_argument('-n',
            dest='N',
            type=int,
            default=4,
            help='Number of wires (default 4)')
            
    parser.add_argument('-c',
            dest='cpus',
            type=int,
            default=1,
            help='Number of cpu''s to use in parallel (def. 1)')
            
    parser.add_argument('-q', '--quiet', 
            dest='quiet',
            help='Operate quietly; do not print to stdout',
            action='store_true')
            
    parser.add_argument('-d',
            dest='datadir',
            default=None,
            help='Parent directory to search for data directories')
            
    args = parser.parse_args()

    print(args)

    # Identify the source directory
    source_dir = None
    if args.source is None:
        raise Exception('A source is required.  Call with --help for more information.')
    # If it is an explicit path to a directory
    elif os.path.isdir(args.source):
        source_dir = args.source
    # Look for a matching data set
    elif args.datadir is not None and os.path.isdir(args.datadir):
        contents = os.listdir(args.datadir)
        # Loop through all contents
        for test_short in contents:
            test_path = os.path.join(args.datadir, test_short)
            # If this one is a match
            if os.path.isdir(test_path) and \
                    test_short.endswith(args.source):
                # If there has not been a match
                if source_dir is None:
                    source_dir = test_path
                else:
                    raise Exception(f'Found multiple matches ending in "{args.source}" in parent directory "{args.datadir}"')
        # Check for a failed match
        if source_dir is None:
            raise Exception(f'Found no matches ending in "{args.source}" in parent directory "{args.datadir}"')
        elif not args.quiet:
            print('Found matching data source: ' + source_dir)
    # No source was found
    else:
        raise Exception(f'Source directory not found.  Did you forget to specify -d?')

    # OK, we've got a source directory, check for prior post1 results
    target_dir = os.path.join(source_dir, target)
    # If it already exists
    if os.path.exists(target_dir):
        if args.force:
            if not args.quiet:
                print('Removing prior post1 results')
            shutil.rmtree(target_dir)
        else:
            raise Exception('Post 1 results already exist. Use -f to overwrite.')
    os.mkdir(target_dir)
    
    # Build a list of worker arguments that include the source data 
    # files and the target output files
    wargs = []
    if not args.quiet:
        print('Found...')
    for dfile in os.listdir(source_dir):
        source = os.path.join(source_dir, dfile)
        if os.path.isfile(source) and\
                dfile.endswith('.dat') and\
                not dfile.startswith('_'):
            print('  ' + dfile)
            target,_,_ = dfile.rpartition('.')
            target = os.path.join(target_dir, target+extension)
            wargs.append({'source':source, 'target':target, 'Nwire':args.N, 'quiet':args.quiet})
        
    # If there is only one worker allowed at a time, do not use multiprocessing
    if args.cpus==1:
        for ww in wargs:
            post1(**ww)
    else:
        # First, determine the number of processes and the number of arguments
        cpus = min(mp.cpu_count(), len(wargs))
        if args.cpus > cpus:
            if not args.quiet:
                print(f'Truncating the number of CPUs to {cpus}.')
        else:
            cpus = args.cpus
            
        with mp.Pool(cpus) as p:
            for ww in wargs:
                p.apply_async(post1, (), ww)
            p.close()
            p.join()
