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
import matplotlib.pyplot as plt
import matplotlib as mpl
import wire


theta_min = -.1
theta_max = .1
theta_step = .0015



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
    verbose     True/False write status updates to stdout?
    view        True/False generate a plot of the results?
"""
    source = workerdata['source']
    theta_min = workerdata['theta_min']
    theta_max = workerdata['theta_max']
    theta_step = workerdata['theta_step']
    wdf = workerdata['wiredata']
    wdlock = workerdata['wdlock']
    verbose_f = workerdata['verbose_f']
    view_f = workerdata['view_f']
    ignore = workerdata['ignore']



    if verbose_f:
        print(f'[{source}] loading')
        
    conf,data = lc.load(source)

    # Extract the wire radii
    maxNwire = 12       # Maximum allowed wires
    wire_r = []         # A record of all wire radii
    Nwire = -1          # number of wires discovered
    for ii in range(maxNwire):
        # Build the meta parameter name that SHOULD specify this wire's radius
        param = f'r{ii}'
        # If it exists, grab the radius
        if param in conf.meta_values:
            wire_r.append(conf.meta_values[param])
        # If the wire meta parameter is NOT found, stop searching
        else:
            Nwire = ii
            break
    
    if Nwire == 0:
        print(f'[{source}] ERROR: no wire radii found in meta parameters', file=sys.stderr)
        return
    elif Nwire < 0:
        print(f'[{source}] ERROR: more than {maxNwire} radii found in meta parameters', file=sys.stderr)
        return
    
    # Calculate the number of theta bins
    wire_theta = np.arange(theta_min+0.5*theta_step, theta_max, theta_step)
    Ntheta = len(wire_theta)

    # We'll use three indexing schemes in this code: 
    #   I - refers to an index in the total raw data set.
    #   J - refers to an index in the down-selected (output) data set
    #   iwire - wire index
    #   ii - is a general purpose index; useage varies
    # There are NXXX integers that determine the bounds on these indices
    #   Ndata - number of raw measurements (I index)
    #   Ntheta - number of theta angle bins
    #   Nwire - number of wires
    
    # Detect the digital input channel
    dich = int(np.log2(conf.distream))
    # First, establish an array of indices that correspond to edge events
    edges_I = data.get_dievents(dich)
    # Get the current signal
    current = data.get_channel(0)
    Ndata = data.ndata()
    
    # Detect the x-, y-, and z-coordinates
    wire_x = conf.meta_values['x']
    wire_z = conf.meta_values['z']
    wire_y = 0.
    
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
    # CCW  |____|< |__|                    |____|  |__|
    #______    __      ____________________    __      ___
    # CW   |__| >|____|                    |__|  |____|
    # 
    # The arrows (<, >) mark the wire-0 edge.
    #
    # CW rotation is considered "positive" so the wires are in natural 
    # order (e.g. 0,1,2,3)  If the rotation is CCW, the wires are in 
    # reverse order (e.g. 0,3,2,1).
    
    # Calculate the number of samples in the intervals between the first
    # five edges (four intervals)
    edges_dI = edges_I[1:5] - edges_I[0:4]
    # Which of them is the longest?  That's the disc rotation
    ii = np.argmax(edges_dI)
    # Now, compare the durations of the two pulses corresponding to the
    # dark stripes.  If the first is the longest, the rotation is CCW
    if edges_dI[(ii+1)%4] > edges_dI[(ii+3)%4]:
        is_ccw = True
        # Find the first wire-0 edge
        ii = (ii+2)%4
        # CCW is "backwards" so we'll index through the data backwards
        current = np.flip(current)
        # Downselect the edges to include only wire-0 edges
        # Reflect the index by Ndata to 
        edges_I = Ndata - 1 - np.flip(edges_I[ii::4])
    # Otherwise, the rotation is CW
    else:
        is_ccw = False
        # Find the first wire-0 edge
        ii = (ii+3)%4
        # Downselect the edges to include only wire-0 edges
        edges_I = edges_I[ii::4]
        
    # edges_I is now an ascending array of indices where the wire-0 was
    # at zero degrees.
    
    # Calculate the samples between complete rotations.
    edges_dI = np.empty_like(edges_I,dtype=int)
    edges_dI[:-1] = np.diff(edges_I)
    edges_dI[-1] = edges_dI[-2]
    # If there is greater than 1% variation, halt - these data are not trustworthy
    if np.max(edges_dI)/np.min(edges_dI) > 1.01:
        print(f'[{source}] WARNING: The disc speed changes by more than 1%.', file=sys.stderr)

    # edges_I is now an array of every index corresponding to 0rad of 
    # disc rotation for wire-0.
    # edges_dI is an array of indices with the number of samples between
    # edges (for a single rotation).  The last element has been 
    # duplicated so it is the same length as edges_I.

    if verbose_f:
        print(f'[{source}] x={wire_x}, y={wire_y}, z={wire_z}, ccw={is_ccw}')
        print(f'    radii: {wire_r}')
    
    # Initialize a 2D list of bins bins to accumulate a histogram
    #   bins[iwire][I]
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
        # Find the index where this wire is at zero radians
        Izero = I + ((iwire-Nwire)*dI) // Nwire
        # Find indices where the wire is in range
        Imin = Izero + int(np.ceil(theta_min / dtheta))
        Imax = Izero + int(np.ceil(theta_max / dtheta))
        # Clip the indices at zero
        Imin = max(0, Imin)
        Imax = max(0, Imax)

        # Loop through the individual measurements
        for ii in range(Imin, Imax):
            # Calculate the sample angle
            theta = (ii-Izero) * dtheta
            # Where does this sample belong?
            J = int(np.floor((theta - theta_min)/theta_step))
            # Force J to be in range
            J = min(J, Ntheta-1)
            bins[iwire][J].append(current[ii])
    
    # Next, loop through the other rotations
    for I, dI, in zip(edges_I, edges_dI):
        # Calculate the angle rotated between each sample
        dtheta = 2*np.pi / dI
        # Loop through wire indices
        for iwire in range(Nwire):
            # Find the index where this wire is at zero radians
            Izero = I + (iwire*dI) // Nwire
            # Find the indices where the wire is in range
            Imin = Izero + int(np.ceil(theta_min / dtheta))
            Imax = Izero + int(np.ceil(theta_max / dtheta))
            
            # Clip the data by the end of the data set
            Imin = min(Ndata, Imin)
            Imax = min(Ndata, Imax)
            
            # use ii for an iterator over individual indices
            for ii in range( Imin, Imax ):
                # Calculate the sample angle
                theta = (ii-Izero) * dtheta
                # Where does this sample belong?
                J = int(np.floor((theta - theta_min)/theta_step))
                # Force J to be in range
                J = min(J, Ntheta-1)
                bins[iwire][J].append(current[ii])
    
    wire_mean = np.zeros((Nwire,Ntheta), dtype=float)
    wire_median = np.zeros((Nwire,Ntheta), dtype=float)
    wire_std = np.zeros((Nwire,Ntheta), dtype=float)
    wire_min = np.zeros((Nwire,Ntheta), dtype=float)
    wire_max = np.zeros((Nwire,Ntheta), dtype=float)
    wire_count = np.zeros((Nwire,Ntheta), dtype=int)
    # Calculate statistics on each bin
    for iwire in range(Nwire):
        for J in range(Ntheta):
            wire_count[iwire,J] = len(bins[iwire][J])
            if(bins[iwire][J]):
                wire_mean[iwire,J] = np.mean(bins[iwire][J])
                wire_median[iwire,J] = np.median(bins[iwire][J])
                wire_std[iwire,J] = np.std(bins[iwire][J])
                wire_min[iwire,J] = np.min(bins[iwire][J])
                wire_max[iwire,J] = np.max(bins[iwire][J])

    
    # If ordered to make images summarizing the data
    if view_f:
        mpl.use('agg')
        if verbose_f:
            print(f'[{source}] plotting')
        fig,ax = plt.subplots(Nwire,2, sharex=True, squeeze=False, figsize=(18,3*Nwire))
        stc = (0.2, 0.2, 0.2)
        for iwire in range(Nwire):
            # Plot the current statistics
            ax[iwire,0].fill_between(wire_theta, 
                    wire_mean[iwire,:]+2*wire_std[iwire,:], 
                    wire_mean[iwire,:]-2*wire_std[iwire,:], 
                    alpha = 0.3, color=stc)
            ax[iwire,0].plot(wire_theta, wire_max[iwire,:], color=stc)
            ax[iwire,0].plot(wire_theta, wire_min[iwire,:], color=stc)
            ax[iwire,0].plot(wire_theta, wire_mean[iwire,:], 'g-')
            ax[iwire,0].plot(wire_theta, wire_median[iwire,:], 'k-')
            ax[iwire,0].set_xlabel('Angle (rad)')
            ax[iwire,0].set_ylabel(f'Current ({data.config.aich[0].aicalunits})')
            ax[iwire,0].grid(True)
            if iwire in ignore:
                ax[iwire,0].set_title(f'Wire {iwire} Statistics - IGNORED')
            else:
                ax[iwire,0].set_title(f'Wire {iwire} Statistics')
            # Plot the histogram
            ax[iwire,1].plot(wire_theta, wire_count[iwire,:], linestyle='none', marker='.', mfc='k', mec='k')
            ax[iwire,1].set_xlabel('Angle (rad)')
            ax[iwire,1].set_ylabel('Data Count')
            ax[iwire,1].grid(True)
            ax[iwire,1].set_title(f'Wire {iwire} Histogram')
        # Build a file name and save it
        # Strip off the file extension
        target,_,_ = source.rpartition('.')
        target = target + '.png'
        fig.savefig(target)
        plt.close(fig)
        
    # Append to the data file
    print(f'[{source}] Writing to output')
    wdlock.acquire()
    try:
        for iwire in range(Nwire):
            # If the index is not to be ignored, include it
            if iwire not in ignore:
                for J in range(Ntheta):
                    wdf.writeline(wire_r[iwire], wire_x, wire_y, wire_theta[J], wire_median[iwire,J])
            # Let the user know we're ignoring a wire
            elif verbose_f:
                print(f'[{source}] NOTICE: ignoring wire {iwire}')
    finally:
        wdlock.release()
        

# If this is being run as a script
if __name__ == '__main__':
    
    # Set up argument parsing
    parser = argparse.ArgumentParser(
            prog='post1.py',
            description='Langmuir probe post processing step 1',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=\
"""The source directory is expected to contain a series of *.dat files with
raw data collected from the Langmuir probe are wire current and a 
digital photo-reflector signal.  The first post processing step 
translates these from a time series of current measurements into current
versus disc angle.

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
            help='The directory containing .dat files from a scan',
            type=str)
            
    parser.add_argument('-f', '--force', 
            dest='force',
            help='Force overwriting prior post1 results',
            action='store_true')

    parser.add_argument('-o', '--output',
            dest='output',
            help='Override the default output file - output.wdf',
            default=None)
            
    parser.add_argument('-c', '--cpus',
            dest='cpus',
            type=int,
            default=1,
            help='Number of cpu''s to use in parallel (def. 1)')
            
    parser.add_argument('-q', '--quiet', 
            dest='quiet',
            help='Operate quietly; do not print to stdout',
            action='store_true')

    parser.add_argument('-i', '--ignore',
            dest='ignore',
            help='Comma-separated list of wire indexes to ignore in the analysis; e.g. "1,2"',
            type=str,
            default=None)

    parser.add_argument('-v', '--view', 
            dest='view',
            help='Generate plots of the wire data',
            action='store_true')
            
    args = parser.parse_args()
    
    # If the output file was not explicitly specified, generate it
    if args.output is None:
        args.output = os.path.join(args.source, 'output.wdf')
    # Does the output file already exist?
    if os.path.isfile(args.output):
        if args.force:
            if not args.quiet:
                print('Warning: File exists - overwriting ' + args.output)
        else:
            raise Exception('(-f to override) File exists: ' + args.output)
    
    # Parse the ignore list (these are wires that will not be analyzed)
    ignore = []
    if args.ignore:
        ignore = [int(this) for this in args.ignore.split(',')]
        
    # Build a list of worker arguments that include the source data 
    # files and the target output files
    wargs = []

    # Create a lock for writing to the data file
    wdlock = mp.Lock()

    # Open the output file
    with wire.WireData(args.output).open('w') as wdf:
        # Loop over all data files
        for dfile in os.listdir(args.source):
            # Establish the path to the current file
            source = os.path.join(args.source, dfile)
            # If this file is a data file (not marked for exclusion
            if os.path.isfile(source) and\
                    dfile.endswith('.dat') and\
                    not dfile.startswith('_'):
                # Build an arguments dictionary for this file
                this_warg = {
                        'source':source, 
                        'theta_min':theta_min,
                        'theta_max':theta_max,
                        'theta_step':theta_step,
                        'wiredata':wdf,
                        'wdlock':wdlock,
                        'verbose_f':not args.quiet,
                        'view_f':args.view,
                        'ignore':ignore}
                wargs.append(this_warg)
            
        # If there is only one worker allowed at a time, do not use multiprocessing
        if args.cpus==1:
            for ww in wargs:
                post1(ww)
        else:
            # First, determine the number of processes and the number of arguments
            cpus = min(args.cpus, mp.cpu_count())
            if not args.quiet:
                print(f'Spawning {cpus} workers.')
                
            # Create a wrapper to call post1
            def worker(*args):
                for a in args:
                    post1(a)
            
            procs = []
            
            breaks = np.linspace(0,len(wargs),cpus+1)
            start = 0
            for c in range(cpus):
                stop = int(round(breaks[c+1]))
                p = mp.Process(target=worker, args=wargs[start:stop])
                p.start()
                procs.append(p)
                start = stop
                
                
            for p in procs:
                p.join()
                
