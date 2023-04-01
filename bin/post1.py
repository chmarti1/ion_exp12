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



def post1(workerdata):
    """Accepts a path to the .dat file to load and a .p1d file to generate
    post1(workerdata)
    
The post processing function loads a raw LConfig data file containing wire
data, and appends it to a WSOLVE wire data file.  The workerdata dictionary
MUST contain the following MANDATORY data elements:

    source      The path to the LConfig data file to read in
    theta_min   The minimum wire angle to include
    theta_max   The maximum wire angle to include
    theta_step  The wire angle increment when binning data
    wiredata    An IOstream to the open wire data file
    wdlock      A lock (mutex) for writing to the file
    quiet       True/False should the function write to stdout?
"""
    source = workerdata['source']
    theta_min = workerdata['theta_min']
    theta_max = workerdata['theta_max']
    theta_step = workerdata['theta_step']
    wdf = workerdata['wiredata']
    wdlock = workerdata['wdlock']
    quiet = workerdata['quiet']

    if not quiet:
        print('[' + source + '] starting...')
        
    conf,data = lc.load(source)

    # Extract the wire radii
    rwire = []
    Nwire = 0
    param = f'r{Nwire}'
    while param in conf.meta_values:
        rwire.append(conf.meta_values[param])
        Nwire += 1
    if Nwire == 0:
        raise Exception('Data file has no wire radii defined: ' + source)
    
    # Calculate the number of theta bins
    Ntheta = int((theta_max - theta_min)//theta_step)
    
    # Detect the digital input channel
    dich = int(np.log2(conf.distream))

    # We'll use three indexing schemes in this code: 
    #   I - refers to an index in the total raw data set.
    #   J - refers to an index in the down-selected (output) data set
    #   ii - is a general purpose index; useage varies

    # First, establish an array of indices that correspond to edge events
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
    
    # (1) Determine the disc direction and identify the wire 1 edge
    # Measure out the durations of the first four intervals (5 edges)
    # The longest interval will correspond to the disc transit
    # _____      __    ____________________      __    ___
    # CW   |____|< |__|                    |____|  |__|
    #______    __      ____________________    __      ___
    # CCW  |__| >|____|                    |__|  |____|
    # 
    # The arrows (<, >) mark the wire-1 edge.
    
    # Calculate the number of samples in the intervals between the first
    # five edges (four intervals)
    edges_dI = edges_I[1:5] - edges_I[0:4]
    # Which of them is the longest?  That's the disc rotation
    ii = np.argmax(edges_dI)
    # Now, compare the durations of the two pulses corresponding to the
    # dark stripes.  If the first is the longest, the rotation is CW
    if edges_dI[(ii+1)%4] > edges_dI[(ii+3)%4]:
        ii = (ii+2)%4
        is_ccw = False
    # Otherwise, the rotation is CCW
    else:
        ii = (ii+3)%4
        is_ccw = True
    # edges_I[ii] is now the index of the first wire-0 edge
    # is_ccw now indicates the direction of disc rotation. When True
    # the wire order will be reversed
    
    # (2) Starting at edges_I[ii], downselect all the edges to isolate 
    # only the wire-0 edges.  Then, calculate the duration between the 
    # edges to establish disc speed during the transits.
    edges_I = edges_I[ii::4]
    # Calculate the samples between complete rotations.
    edges_dI = np.empty_like(edges_I,dtype=int)
    edges_dI[:-1] = np.diff(edges_I)
    edges_dI[-1] = edges_dI[-2]
    # If there is greater than 1% variation, there is a problem.
    if np.max(edges_dI)/np.min(edges_dI) > 1.01:
        raise Exception('The disc speed varied by more than 1% in file: ' + source)
    # edges_I is now an array of every index corresponding to 0rad of 
    # disc rotation for wire-0.
    # edges_dI is an array of indices with the number of samples between
    # edges (for a single rotation).  The last element has been 
    # duplicated so it is the same length as edges_I.
    
    # Initialize bins to accumulate a histogram for 

    bins = [[ [] for _ in range(Ntheta)] for _ in range(Nwire)]
    
    # Before we loop over the bulk of the data, we'll look at data before
    # the first trigger event.
    # Let I be the index of the first wire-0 trigger event.  dI is the
    # number of samples betweeen trigger events
    I = edges_I[0]
    dI = edges_dI[0]
    # Calculate the angle rotated between each sample
    dtheta = 2*np.pi / dI
    # Loop through wire indices
    for iwire in range(Nwire):
        # Izero, Imin, and Imax are the data indices where the wire angle
        # is zero, theta_min, and theta_max.
        Izero = I - ((Nwire-iwire)*dI) // Nwire
        Imin = max(0, Izero + int(theta_min / dtheta))
        Imax = max(0, Izero + int(theta_max / dtheta))
        # Loop through the individual measurements
        for ii in range(Imin, Imax+1):
            # Calculate the sample angle
            theta = (ii-Izero) * dtheta
            # Where does this sample belong?
            J = int(np.floor((theta - theta_min)/theta_step))
            bins[iwire][J].append(current[ii])
    
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
                # Calculate the sample angle
                theta = (ii-Izero) * dtheta
                # Where does this sample belong?
                J = int(np.floor((theta - theta_min)/theta_step))
                bins[iwire][J].append(current[ii])
    
    wire_mean = np.empty((Nwire,Ntheta), dtype=float)
    wire_median = np.empty((Nwire,Ntheta), dtype=float)
    wire_std = np.empty((Nwire,Ntheta), dtype=float)
    wire_min = np.empty((Nwire,Ntheta), dtype=float)
    wire_max = np.empty((Nwire,Ntheta), dtype=float)
    # Calculate statistics on each bin
    for iwire in range(Nwire):
        for J in range(Ntheta):
            wire_mean[iwire,J] = np.mean(bins[iwire][J])
            wire_median[iwire,J] = np.median(bins[iwire][J])
            wire_std[iwire,J] = np.std(bins[iwire][J])
            wire_min[iwire,J] = np.min(bins[iwire][J])
            wire_max[iwire,J] = np.max(bins[iwire][J])
            
    # Construct an output dictionary
    wire = {
        'r':rwire,
        'theta':np.arange(0.5, Ntheta, 1.0) * dtheta + theta_min,
        'mean':wire_mean,
        'median':wire_median,
        'std':wire_std,
        'min':wire_min,
        'max':wire_max,
    }
    return wire
    

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
