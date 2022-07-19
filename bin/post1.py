#!/usr/bin/python3

import os,sys
import lconfig as lc
import numpy as np
import pickle

datadir = '../data'

theta_min = -0.3
theta_max = +0.3
Nwire = 4

def worker(source, target):
    """Accepts a path to the .dat file to load and post-process
"""

    print('Loading...')
    conf,data = lc.load(source)

    print('Edge detection...')
    # Detect the digital input channel
    dich = int(np.log2(conf.distream))

    # First, establish the edge events
    edges_I = data.get_dievents(dich)
    # Then, get the time and current arrays
    time = data.time()
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
    
    print('Output...')
    # Initialize a result - we'll write it with json
    out = [{'theta':[], 'current':[]} for ii in range(Nwire)]
    
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
            out[iwire]['theta'].append((ii - Izero) * dtheta)
            out[iwire]['current'].append(current[ii])
    
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
                out[iwire]['theta'].append((ii - Izero) * dtheta)
                out[iwire]['current'].append(current[ii])

    with open(target, 'w') as ff:
        pickle.dump(out, ff)
