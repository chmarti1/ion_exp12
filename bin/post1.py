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
import wire


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
    view_f = workerdata['view']


    if verbose_f:
        print(f'[{source}] starting.')
        
    conf,data = lc.load(source)

    # Extract the wire radii
    wire_r = []
    Nwire = 0
    param = f'r{Nwire}'
    while param in conf.meta_values:
        wire_r.append(conf.meta_values[param])
        Nwire += 1
    if Nwire == 0:
        print(f'[{source}] ERROR: no wire radii found in meta parameters', file=sys.stderr)
        return
    
    # Calculate the number of theta bins
    Ntheta = int((theta_max - theta_min)//theta_step)

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
        ii = (ii+2)%4
        is_ccw = True
    # Otherwise, the rotation is CW
    else:
        ii = (ii+3)%4
        is_ccw = False
        # Adjust the wire radius order
        wire_r.reverse()
        wire_r.insert(0, r.pop(-1))
        
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
    # If there is greater than 1% variation, halt - these data are not trustworthy
    if np.max(edges_dI)/np.min(edges_dI) > 1.01:
        print(f'[{source}] ERROR: The disc speed changes by more than 1%.', file=sys.stderr)
        return
    # edges_I is now an array of every index corresponding to 0rad of 
    # disc rotation for wire-0.
    # edges_dI is an array of indices with the number of samples between
    # edges (for a single rotation).  The last element has been 
    # duplicated so it is the same length as edges_I.
    
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
    # If rotation is backwards, dtheta is negative
    if is_ccw:
        dtheta = -dtheta
    # Loop through wire indices
    for iwire in range(Nwire):
        # Izero, Imin, and Imax are the data indices where the wire angle
        # is zero, theta_min, and theta_max.  
        Izero = I - ((Nwire-iwire)*dI) // Nwire
        Imin = max(0, Izero + int(theta_min / dtheta))
        Imax = max(0, Izero + int(theta_max / dtheta))
        # If rotation is reversed, reverse the indices
        if is_ccw:
            temp = Imin
            Imin = Imax
            Imax = temp

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
        # If rotation is backwards, dtheta is negative
        if is_ccw:
            dtheta = -dtheta
        # Loop through wire indices
        for iwire in range(Nwire):
            Izero = I + (iwire*dI) // Nwire
            Imin = min(Ndata-1, Izero + int(theta_min / dtheta))
            Imax = min(Ndata-1, Izero + int(theta_max / dtheta))
            # If rotation is reversed, reverse the indices
            if is_ccw:
                temp = Imin
                Imin = Imax
                Imax = temp
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
    wire_count = np.empty((Nwire,Ntheta), dtype=int)
    wire_theta = np.arange(theta_min+0.5*dtheta, theta_max, dtheta)
    # Calculate statistics on each bin
    for iwire in range(Nwire):
        for J in range(Ntheta):
            wire_mean[iwire,J] = np.mean(bins[iwire][J])
            wire_median[iwire,J] = np.median(bins[iwire][J])
            wire_std[iwire,J] = np.std(bins[iwire][J])
            wire_min[iwire,J] = np.min(bins[iwire][J])
            wire_max[iwire,J] = np.max(bins[iwire][J])
            wire_count[iwire,J] = len(bins[iwire][J])
    
    # If ordered to make images summarizing the data
    if view_f:
        fig,ax = plt.subplots((Nwire,2), sharex=True, squeeze=False, figsize=(3*Nwire,4))
        stc = (0.2, 0.2, 0.2)
        for iwire in range(Nwire):
            # Plot the current statistics
            ax[iwire,0].fill_between(wire_theta, 
                    wire_mean+2*wire_std, 
                    wire_mean-2*wire_std, 
                    alpha = 0.3, color=stc)
            ax[iwire,0].plot(wire_theta, wire_max[iwire,:], color=stc)
            ax[iwire,0].plot(wire_theta, wire_min[iwire,:], color=stc)
            ax[iwire,0].plot(wire_theta, wire_mean[iwire,:], 'g-')
            ax[iwire,0].plot(wire_theta, wire_median[iwire,:], 'k-')
            ax[iwire,0].set_xlabel('Angle (rad)')
            ax[iwire,0].set_ylabel(f'Current ({data.aich[0].aicalunits})')
            ax[iwire,0].grid(True)
            ax[iwire,0].set_title(f'Wire {iwire} Statistics')
            # Plot the histogram
            ax[iwire,1].plot(wire_theta, wire_count[iwire,:], linestyle='none', ms='.', mc='k')
            ax[iwire,1].set_xlabel('Angle (rad)')
            ax[iwire,1].set_ylabel('Data Count')
            ax[iwire,1].grid(True)
            ax[iwire,0].set_title(f'Wire {iwire} Histogram')
        # Build a file name and save it
        # Strip off the file extension
        target,_,_ = source.rpartition('.')
        target = target + '.png'
        fig.savefig(target)
        
    # Append to the data file
    wdlock.acquire()
    try:
        for iwire in range(Nwire):
            for J in range(Ntheta):
                wdf.writeline(wire_r[iwire], wire_x, wire_y, wire_theta[J], wire_median[J])
    finally:
        wdlock.release()
        

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
            help='The directory containing .dat files from a scan',
            default=None)
            
    parser.add_argument('-f', '--force', 
            dest='force',
            help='Force overwriting prior post1 results',
            action='store_true')
            
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
    
    # Build a list of worker arguments that include the source data 
    # files and the target output files
    wargs = []
    contents = os.listdir(source_dir)
    
    for dfile in os.listdir(source_dir):
        source = os.path.join(source_dir, dfile)
        if os.path.isfile(source) and\
                dfile.endswith('.dat') and\
                not dfile.startswith('_'):
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
