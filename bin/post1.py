#!/usr/bin/python3

import os,sys
import lconfig as lc
import numpy as np

datadir = '../data'

theta_min = -0.3
theta_max = +0.3

def worker(target):
    """Accepts a path to the .dat file to load and post-process
"""

    conf,data = lc.load(target)

    # Detect the digital input channel
    dich = int(np.log2(conf.distream))

    # First, establish the edge events
    edges_I = data.get_dievents(dich)
    # Then, get the time and current arrays
    time = data.time()
    current = data.get_channel(0)
    
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
    edges_dI = np.empty_like(edges_I,dtype=float)
    edges_dI[:-1] = np.diff(edges_I)
    edges_dI[-1] = edges_dI[-2]
    # If there is greater than 1% variation, there is a problem.
    if np.max(edges_dI)/np.min(edges_dI) > 1.01:
        raise Exception('The disc speed varied by more than 1% in file: ' + target)
    
    # Finally, calculate the angular displacement per sample for each
    # of the edges.  This value should be nearly identical for every
    # edge, but if the disc speed shows drift, this approach will 
    # compensate for it.
    dtheta = 2*np.pi / edges_dI
    
    # Look for any wire events before the first edge
    dI = edges_dI[0]
    dtheta = 2*np.pi / dI
    # Wire 1
    Ix = edges_I[0] - dI
    if Ix > 0:
        Istart = int(theta_min / dtheta)
        Istop = int(theta_max / dtheta)
    # Wire 2
    
    # Loop over the edges
    for I,dI in zip(edges_I[:-1], edges_dI[:-1]):
        I1 = I
        I2 = I1 + dI // 4
        I3 = I1 + dI // 2
        I4 = I1 + (dI*3) // 4
    
    return dt
