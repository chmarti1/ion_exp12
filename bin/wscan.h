#include "lconfig.h"
#include <unistd.h>

/* AxisIterator
 *  A struct to manage axis motion using stepper motors. It requires an
 * LConfig LC_DEVCONF_T struct configured with a pulse out channel (for
 * steps) and a direction channel (for direction).
 * 
 * 
 */

#ifndef __WSCAN_H__
#define __WSCAN_H__

#define AX_STR          64          // Standard string length
#define AX_SETTLE_US    100000      // Time to wait for the axis motion to settle

typedef struct _AxisIterator {
    lc_devconf_t    *dconf; // The LConfig device configuration
    int             efch;   // The extended feature channel for the pulse out
    char            dregister[AX_STR];   // The LJM register for the direction bit
    int             state;  // The current axis position
    double          cal;    // Calibration (length per count)
    char            units[LCONF_MAX_STR];  // Calibration units
    int             steps;  // The steps per each motion
    int             niter;  // Number of iterations in a scan
    int             dpos;   // Direction bit value when moving in the positive axis
    // These are "live" parameters in use during a scan
    int             _dir;   // Direction of motion
    int             _index; // Number of iterations performed
} AxisIterator_t;


/* AX_INIT - Initialize the axis from an LCONFIG device
 * 
 * This associates an AxisIterator struct with a pulse out extended 
 * feature channel configured in the LCONFIG device.  It automatically 
 * assigns the next DIO channel as the direction channel.  The behavior
 * of the scan iterator is also automatically read from the LConfig 
 * meta data with the field names automatically constructed from the
 * "axis" character.
 * 
 * When the axis character is 'X', required meta data are:
 * NAME     : [type] (restrictions) description
 * ----------------------------------------------------------------------
 * Xdir     : [int] (1 or 0) indicates which direction is positive motion
 * Xstep    : [int] (none)  Steps per motion (can be negative)
 * Xn       : [int] (>0)    Intervals to scan (Xn + 1 locations)
 * Xcal     : [float] (>0)  Calibration in length per count
 * Xunits   : [str] (<63 char) Unit length string
 * 
 * efch : the extended feature channel to associate with this axis.  It
 *        must be configured as a pulse output.  Note that the direction
 *        pin will automatically be set as (dconf[efch].channel + 1)
 *
 * axis : a single-character used to identify the mandatory meta 
 *        configuration parameters in the LConfig struct.
 * 
 * Returns 0 on Success.
 * Returns -1 on failure.
 */
int ax_init(AxisIterator_t *ax, lc_devconf_t *dconf, int efch, char axis){
    int dirch;
    char stemp[AX_STR];
    
    ax->state = 0;
    ax->_index = -1;
    ax->_dir = 1;
    
    ax->dconf = dconf;
    // Is the efch number in range?
    if(efch < 0 || efch >= dconf->nefch){
        fprintf(stderr, "AX_INIT: extended feature channel (%d) is out of range [0,%d)\n", efch, dconf->nefch);
        return -1;
    // Make sure the extended feature channel is a pulse output
    }else if(dconf->efch[efch].signal != LC_EF_COUNT || dconf->efch[efch].direction != LC_EF_OUTPUT){
        fprintf(stderr, "AX_INIT: extended feature channel (%d) is not configured as a pulse output.\n", efch);
        return -1;
    }
    ax->efch = efch;
    // Automatically use the digital output channel next to the EF channel
    // for the direction bit
    dirch = dconf->efch[efch].channel+1;
    // Verify that the direction pin is configured to an output
    if(! (dconf->domask & 1<<dirch)){
        fprintf(stderr, "AX_INIT: direction pin, DIO%d, is not configured as an output.\n", dirch);
        return -1;
    }
    // stash the direction register name for later
    sprintf(ax->dregister, "DIO%d", dconf->efch[efch].channel+1);

    // Retrieve the configuration parameters from the LConfig meta variables
    // STEPS
    sprintf(stemp, "%cstep", axis);
    if(lc_get_meta_int(dconf, stemp, &ax->steps)){
        fprintf(stderr, "AX_INIT: Did not find required meta configuration parameter: %s\n", stemp);
        return -1;
    }
    // NITER
    sprintf(stemp, "%cn", axis);
    if(lc_get_meta_int(dconf, stemp, &ax->niter)){
        fprintf(stderr, "AX_INIT: Did not find required meta configuration parameter: %s\n", stemp);
        return -1;
    }else if(ax->niter <= 0){
        fprintf(stderr, "AX_INIT: %cn set to %d. Must be positive.\n", axis, ax->niter);
        return -1;
    }
    // DPOS
    sprintf(stemp, "%cdir", axis);
    if(lc_get_meta_int(dconf, stemp, &ax->dpos)){
        fprintf(stderr, "AX_INIT: Did not find required meta configuration parameter: %s\n", stemp);
        return -1;
    }
    ax->dpos = (ax->dpos != 0); // Force dpos to be 1 or 0
    // CAL
    sprintf(stemp, "%ccal", axis);
    if(lc_get_meta_flt(dconf, stemp, &ax->cal)){
        fprintf(stderr, "AX_INIT: Did not find required meta configuration parameter: %s\n", stemp);
        return -1;
    }else if(ax->cal <= 0){
        fprintf(stderr, "AX_INIT: %ccal set to %lf.  Must be positive.\n", axis, ax->cal);
        return -1;
    }
    // UNITS
    if(lc_get_meta_str(dconf, "unit_length", ax->units)){
        fprintf(stderr, "AX_INIT: Did not find required meta configuration parameter: unit_length\n");
        return -1;
    }

    return 0;
}



/* AX_MOVE - Move the axis a number of steps without iteration
 * 
 * Without needing to call AX_ITER_BEGIN() or AX_ITER(), just command
 * motion in the axis.
 * 
 *   steps : The number of steps by which to move the axis.  Direction
 *           is indicated by the sign of steps.
 * 
 * wait_us : The number of microseconds to wait before returning for the
 *           motion to complete.  Set to 0 to disable the wait, and set
 *           to a negative value to automatically calculate the value 
 *           from the number of pulses.  AX_SETTLE_US is added to the
 *           calculated value to ensure that any remaining vibration has
 *           subsided.
 */
int ax_move(AxisIterator_t *ax, int steps, int wait_us){
    int dir, psteps, err;
    
    // Recode steps from +/- into a direction bit and a positive
    // number of steps
    // If holding position, do nothing
    if(steps == 0)
        return 0;
    // If in the negative direction
    else if(steps < 0){
        psteps = -steps;
        dir = ! ax->dpos;
    // If in the positive direction
    }else{
        psteps = steps;
        dir = ax->dpos;
    }
    
    // Write to the direction bit
    err = LJM_eWriteName(ax->dconf->handle, ax->dregister, dir);
    if(err){
        fprintf(stderr, "AX_MOVE: Failed to set direction pin on %s\n", ax->dregister);
        return -1;
    }
    // Send the pulse count
    ax->dconf->efch[ax->efch].counts = psteps;
    err = lc_update_ef(ax->dconf);
    if(err){
        fprintf(stderr, "AX_MOVE: Failed to transmit pulse out\n");
        return -1;
    }
    
    // Update the axis state
    ax->state += steps;
    
    // Case out the wait 
    // If wait is negative, we'll calculate it
    if(wait_us < 0){
        usleep((int)(psteps * 1e6 / ax->dconf->effrequency) + AX_SETTLE_US);
    // If wait is positive, just wait that long
    }else if(wait_us > 0){
        usleep(wait_us);
    }
    // If wait is zero, don't wait.
    return 0;
}


/* AX_ITER_START - set up the first motion in an axis
 * AX_ITER_REPEAT - repeat the last iteration, but backwards
 *
 * These set up the struct for repeated (iterated) motions comprising a
 * scan.  AX_ITER_START() is always called the first time an axis 
 * executes a scan.  To repeat the scan in the same direction, 
 * AX_ITER_START() can be called again, and the axis will be commanded 
 * back to its original starting position to initiate the scan.
 * 
 * Alternately, if subsequent scans are always conducted in the opposite
 * direction, the axis does not need to back-track over its position.
 * AX_ITER_REPEAT sets up another iteration just like AX_ITER_START, but
 * it always reverses the last direction taken.
 * 
 * Note that the initial scan can still be configured to be in the 
 * negative direction on the axis if the Xsteps parameter is negative.
 * 
 * Neither AX_ITER_START() nor AX_ITER_REPEAT() commands motion.  They 
 * merely refresh the _index and _dir parameters that are used by the
 * AX_ITER() function to manage the scan.
 *
 * Returns 0 always
 */
int ax_iter_start(AxisIterator_t *ax){
    ax->_dir = 1;
    ax->_index = -1;
    return 0;
}

int ax_iter_repeat(AxisIterator_t *ax){
    ax->_dir = !ax->_dir;
    ax->_index = -1;
    return 0;
}

/* AX_ITER - iterate through a series of equal motions on an axis
 * 
 * Only call AX_ITER() after calling AX_ITER_START() or AX_ITER_REPEAT()
 * to define the motion plan.
 *
 * Each call to AX_ITER() attempts to command one of the configured 
 * motions.  First, AX_ITER() checks to be certain that the motions
 * in the motion plan have not already been exhausted.  If so, it returns
 * 1, and no motion is commanded.  Otherwise, the AX_MOVE() function is
 * called to command the appropriate motion, and 0 is returned.
 *  
 * wait_us : The number of microseconds to wait before returning for the
 *           motion to complete.  Set to 0 to disable the wait, and set
 *           to a negative value to automatically calculate the value 
 *           from the number of pulses.  AX_SETTLE_US is added to the
 *           calculated value to ensure that any remaining vibration has
 *           subsided.
 * 
 * Returns:
 *  0 on success
 *  1 on iteration complete
 *  -1 on an error 
 */
int ax_iter(AxisIterator_t *ax, int wait_us){
    int distance;
    
    // Test for iteration complete
    if(ax->_index >= ax->niter)
        return 1;
    
    // Increment the index
    ax->_index ++;
    
    // Calculate the desired location
    if(ax->_dir)
        distance = ax->_index * ax->steps;
    else
        distance = (ax->niter - ax->_index) * ax->steps;
    // Adjust to find the distance required
    distance -= ax->state;
    
    return ax_move(ax, distance, wait_us);
}

/* AX_GET_POS   - Return the position in length units
 * AX_GET_INDEX - Return the current index in the iteration
 * 
 */
double ax_get_pos(AxisIterator_t *ax){
    return ax->state * ax->cal;
}

int ax_get_index(AxisIterator_t *ax){
    return ax->_index;
}

#endif
