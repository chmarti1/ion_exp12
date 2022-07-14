#include "lconfig.h"
#include <unistd.h>
#include <sys/stat.h>
#include <time.h>
#include <errno.h>
#include <string.h>


#define CONFIG_DEFAULT  "wscan.conf"
#define STR_LEN         128
#define STR_SHORT       32
#define XPULSE_EF       0
#define ZPULSE_EF       1
#define XDIR_POS        1
#define ZDIR_POS        1
#define TSETTLE_US      100000  // Time for mechanical vibration to settle before taking data



char help_text[] = "wscan [-h] [-c CONFIG] [-d DEST] [-i|f|s PARAM=VALUE] \n"\
"  Conducts an ion density scan of a region in space by alternatively\n"\
"commanding motion of the spinning disc Langmuir probe and collecting\n"\
"data.  The data acquisition process is configured in an LCONFIG file\n"\
"that is \"wscan.conf\" by default.\n"\
"\n"\
"To work properly, WSCAN requires the configuration file to contain\n"\
"certain mandatory elements:\n"\
" - There must be a single analog input. It will be the wire current\n"\
" - Digital input streaming must be active for the disc encoder signal\n"\
" - Two digital pulse/count outputs must be configured (extended features)\n"\
"   These are the x and z step commands (in that order). They must be at\n"\
"   least one channel appart, because the channel above each will be used\n"\
"   for the channel direction. For example, if the x pulse output were\n"\
"   set to DIO2, then DIO3 will be used for the x direction.\n"\
" - There must be meta parameters with the following names:\n"\
"   \"xstep\" (int): The x-axis increment in pulses (+/-).\n"\
"   \"xn\" (int): The number of x-axis scan locations (min 1).\n"\
"   \"zstep\" (int): The z-axis increment in pulses (+/-).\n"\
"   \"zn\" (int): The number of z-axis scan locations (min 1).\n"\
"   These define a grid of disc locations in the x-z plane.  The x-axis\n"\
"   is assumed to have been carefully aligned with the plane of disc\n"\
"   rotation. The z-axis is roughly (but not necessarily precisely) \n"\
"   perpendicular to the plane of disc rotation.\n"\
"\n"\
"The data collection will begin wherever the system is positioned when\n"
"wscan begins. Each measurement will be written to its own dat file in\n"
"the target directory, and the files are named by number in the order \n"
"they were collected. \n"
"-h\n"\
"  Displays this help text and exits.\n"\
"\n"\
"-c CONFIG\n"\
"  By default, uses \"wscan.conf\" in the current directory, but -c\n"\
"specifies an alternate configuration file.\n"\
"\n"\
"-d DEST\n"\
"  Specifies a destination directory for the data files. By default, one\n"\
"will be created using the timestamp, but if this argument is present, it\n"\
"will be used instead.\n"\
"\n"\
"-i\n"\
"-f\n"\
"-s\n"\
"  Inserts a meta parameter from the command line. The flag 'i', 'f', or \n"\
"'s' identifies the data type as integer, float, or string respectively.\n"\
"The following parameter specifies both the parameter name and its value\n"\
"split by the '=' character. For example,\n"\
"    -i index=12 -s name=Chris\n"\
"specifies a meta integer named \"index\" and a meta string named \"name\".\n"\
"These will be inserted into the data files whether or not they were in the\n"\
"original configuration file.\n"\
"\n"\
"(c)2022  Christopher R. Martin\n";


int main(int argc, char *argv[]){
    int ch,             // holds the character for the getopt system
        err,            // error index
        xdir_dioch,     // LabJack DIO channel for the x-direction bit
        xstep,          // grid increment in pulses
        xdir,           // +1 or -1 depending
        xn,             // number of grid nodes
        xi,             // x grid index
        x0,             // x start location
        xwaitus,        // Time for x motion in microseconds
        zdir_dioch,     // LabJack DIO channel for the z-direction bit
        zstep,          // grid increment in pulses
        zdir,           // +1 or -1 depending
        zn,             // number of grid nodes
        zi,             // z grid index
        z0,             // z start location
        zwaitus,        // Time fo z motion in microseconds
        file_counter;   // index for generating file names
    char config_filename[STR_LEN], 
        dest_directory[STR_LEN],
        filename[STR_LEN],
        stemp[STR_SHORT],
        stemp1[STR_SHORT];
    double ftemp;
    int itemp;
    
    time_t now;
    struct stat dirstat;
    lc_devconf_t dconf;
    FILE *fd;
    
    
    config_filename[0] = '\0';
    dest_directory[0] = '\0';
    
    // Parse the options
    while((ch = getopt(argc, argv, "hc:d:i:s:f:")) >= 0){
        switch(ch){
        case 'h':
            printf(help_text);
            return 0;
        case 'c':
            strcpy(config_filename, optarg);
        break;
        case 'd':
            strcpy(dest_directory, optarg);
        break;
        case 'i':
        case 's':
        case 'f':
            // Do nothing; we'll handle these later
        break;
        default:
            fprintf(stderr, "WSCAN: Unrecognized option %c\n", (char) ch);
            return -1;
        break;
        }
    }

    // If the configuration file is not specified, use the default
    if(!config_filename[0])
        strcpy(config_filename, CONFIG_DEFAULT);
    // If the destination directory is not specified, build one from the timestamp
    if(!dest_directory[0]){
        time(&now);
        strftime(dest_directory, STR_LEN, "%04Y%02m%02d%02H%02M%02S", localtime(&now));
    }
    // Load the configuration file.
    if(lc_load_config(&dconf, 1, config_filename))
        return -1;
        
        
    // Go back and apply any meta configuration parameters
    optind = 1;
    while((ch = getopt(argc, argv, "hc:d:i:s:f:")) >= 0){
        switch(ch){
        case 'h':
        case 'c':
        case 'd':
            // These have already been dealt with
        break;
        case 'i':
            if(sscanf(optarg, "%[^=]=%d", stemp, &itemp) != 2){
                fprintf(stderr, "WSCAN: Failed to parse integer meta argument: %s\n", optarg);
                lc_close(&dconf);
                return -1;
            }
            if(lc_put_meta_int(&dconf, stemp, itemp)){
                fprintf(stderr, "WSCAN: WARNING! Failed to set integer parameter, %s=%d\n", stemp, itemp); 
            }
        break;
        case 's':
            if(sscanf(optarg, "%[^=]=%s", stemp, stemp1) != 2){
                fprintf(stderr, "WSCAN: Failed to parse string meta argument: %s\n", optarg);
                return -1;
            }
            if(lc_put_meta_str(&dconf, stemp, stemp1)){
                fprintf(stderr, "WSCAN: WARNING! Failed to set string parameter, %s=%s\n", stemp, stemp1);
            }
        break;
        case 'f':
            if(sscanf(optarg, "%[^=]=%lf", stemp, &ftemp) != 2){
                fprintf(stderr, "WSCAN: Failed to parse float meta argument: %s\n", optarg);
                return -1;
            }
            if(lc_put_meta_flt(&dconf, stemp, ftemp)){
                fprintf(stderr, "WSCAN: WARNING! Failed to set float parameter, %s=%f\n", stemp, ftemp);
            }
        break;
        default:
            fprintf(stderr, "WSCAN: Unexpected condition! Unrecognized option %c\n", (char) ch);
            return -1;
        break;
        }
    }    
        
    // Verify the extended feature channels
    if(dconf.nefch < 2){
        fprintf(stderr, "WSCAN: Requires two extended feature channels, found %d\n", dconf.nefch);
        return -1;
    }else if(dconf.efch[0].signal != LC_EF_COUNT || dconf.efch[0].direction != LC_EF_OUTPUT){
        fprintf(stderr, "WSCAN: The first EF channel was not a COUNT output.\n");
        return -1;
    }else if(dconf.efch[1].signal != LC_EF_COUNT || dconf.efch[1].direction != LC_EF_OUTPUT){
        fprintf(stderr, "WSCAN: The second EF channel was not a COUNT output.\n");
        return -1;
    }
    
    // Establish the direction channel numbers as next to their corresponding pulse channels
    xdir_dioch = dconf.efch[XPULSE_EF].channel + 1;
    zdir_dioch = dconf.efch[ZPULSE_EF].channel + 1;

    // Retrieve mandatory meta parameters
    //   These define an x,z grid of probe locations to scan.
    // xstep and zstep are the number of stepper motor steps to move
    // between grid locations.  xn and zn are the number of grid 
    // locations for each.
    if(     lc_get_meta_int(&dconf, "xstep", &xstep) ||
            lc_get_meta_int(&dconf, "xn", &xn) ||
            lc_get_meta_int(&dconf, "zstep", &zstep) ||
            lc_get_meta_int(&dconf, "zn", &zn)){
        fprintf(stderr, "WSCAN: Missing mandatory meta configuration parameter(s): xstep, xn, zstep, or zn\n");
        return -1;
    // Do a little sanity checking
    }else if(zn <= 0 || xn <= 0){
        fprintf(stderr, "WSCAN: xn and zn must be positive. Found: xn=%d zn=%d\n", xn, zn);
        return -1;
    }

    // Open the device connection
    if(lc_open(&dconf)){
        fprintf(stderr, "WSCAN: Failed to open the device connection.\n");
        return -1;
    }
    // Upload the device configuration
    if(lc_upload_config(&dconf)){
        fprintf(stderr, "WSCAN: Configuration upload failed.\n");
        lc_close(&dconf);
        return -1;
    }

    // If the target directory does not exist, then create it
    err = stat(dest_directory, &dirstat);
    // If the directory doesn't exist, create it
    if(err){
        if(mkdir(dest_directory, 0755)){
            fprintf(stderr, "WSCAN: Failed to create directory: %s\n", dest_directory);
            lc_close(&dconf);
            return -1;
        }
    // If the destination appears to be a file, raise an error
    }else if(!S_ISDIR(dirstat.st_mode)){
        fprintf(stderr, "WSCAN: The destination directory appears to be a file: %s\n", dest_directory);
        lc_close(&dconf);
        return -1;
    // If the directory already exists, warn the user
    }else{
        fprintf(stderr, "WSCAN: WARNING! The destination directory already exists: %s\n", dest_directory);
        ch = '?';
        while(ch != 'Y'){
            printf("Overwrite existing data?  (Y/n):");
            scanf("%c", (char*) &ch);
            if(ch == 'Y'){
                printf("... overwriting ...\n");
            }else if(ch == 'n'){
                printf("... aborting ...\n");
                return 0;
            }else{
                printf("... unexpected response.  Please enter 'Y' or 'n'.\n");
            }
        }
    }

    // Set the direction bits to be outputs
    err = LJM_eWriteName(dconf.handle, "DIO_DIRECTION", 1<<xdir_dioch | 1<<zdir_dioch);
    
    /* Initialize the direction of motion based on the x- and z-step 
    signs.  We will force the step sizes to be positive, but the 
    hardware pins should be set appropriately, and we'll initialize
    the xi and zi indices to be at their maximum or minimum based
    on the initial direction of motion.  This is especially important
    for the x-direction, since it will reverse itself after each 
    plane.
    
    xi and zi are counters that indicate the x- and z-grid-numbers.  If
    the steps are negative, then they will start at their maximum (xn-1 
    or zn-1) and decrease.  Otherwise, they start at zero and increase.
    x0 and z0 are the grid numbers where the scan began.  When the scan
    is complete, the stages will return to this position.
    
    xdir and zdir are +1 or -1 to indicate the current direction of scan.
    zdir will never change, but xdir will change signs at the end of 
    every grid row.  To eliminate redundant code segments, the loops are
    constructed as while(1) with a break condition.
    
    xstep and zstep are the number of pulses to transmit between grid 
    features, so they must always be positive.  Direction information
    is exclusively contained in xdir and zdir.
    */
    
    // Initialize the relevant registers and set the x and z direction
    // bits.  The z-direction bit will never need to be changed until 
    // the stages return to their original positions at the end.
    sprintf(stemp, "DIO%d", xdir_dioch);
    if(xstep < 0){
        xstep = -xstep;
        xdir = -1;
        xi = xn-1;
        err = err ? err : LJM_eWriteName(dconf.handle, stemp, !XDIR_POS);
    }else{
        xdir = 1;
        xi = 0;
        err = err ? err : LJM_eWriteName(dconf.handle, stemp, XDIR_POS);
    }

    sprintf(stemp, "DIO%d", zdir_dioch);        
    if(zstep < 0){
        zstep = -zstep;
        zdir = -1;
        zi = zn-1;
        err = err ? err : LJM_eWriteName(dconf.handle, stemp, !ZDIR_POS);        
    }else{
        zdir = 1;
        zi = 0;
        err = err ? err : LJM_eWriteName(dconf.handle, stemp, ZDIR_POS);
    }
    
    if(err){
        fprintf(stderr, "WSCAN: Failed to initialize the motor direction pins. Aborting\n");
        lc_close(&dconf);
        return -1;
    }
    
    // Log the starting locations. We will return here later.
    x0 = xi;
    z0 = zi;
    
    // Calculate wait times
    xwaitus = xstep * 1e6 / dconf.effrequency + TSETTLE_US;
    zwaitus = zstep * 1e6 / dconf.effrequency + TSETTLE_US;
    
    // Loop through the entire grid array
    // An out-of-bounds check is necessary to decide whether to command
    // movement and whether to jump out of the loop.  To eliminate 
    // redundant
    // z-loop
    while(1){
        // x-loop
        while(1){
            // Let the user know what's going on
            printf("xi = %d (%d), zi = %d (%d)\n", xi, xn, zi, zn);
            // Record the current z and x indices
            if(lc_put_meta_int(&dconf, "xi", xi) || lc_put_meta_int(&dconf, "zi", zi)){
                fprintf(stderr, "WSCAN: WARNING! Failed to write the xi or zi meta values prior to data acquisition\n");
            }
            
            // Read data in a burst configuration: start, service, stop
            if(lc_stream_start(&dconf, -1)){
                fprintf(stderr, "WSCAN: Failed to start data stream. Aborting\n");
                lc_close(&dconf);
                return -1;
            }
            // Keep going until the collection is complete
            while( !lc_stream_iscomplete(&dconf) ){
                if(lc_stream_service(&dconf)){
                    fprintf(stderr, "WSCAN: Unexpected error while streaming data. Aborting\n");
                    lc_stream_stop(&dconf);
                    lc_close(&dconf);
                    return -1;
                }
            }
            lc_stream_stop(&dconf);
            
            // construct the file name and open it.  Only write if the 
            // open operation is complete.
            sprintf(filename, "%s/%03d_%03d.dat", dest_directory, xi, zi);            
            fd = fopen(filename, "wb");
            if(fd){
                // Write the data file
                lc_datafile_init(&dconf, fd);
                while( !lc_stream_isempty(&dconf) )
                    lc_datafile_write(&dconf, fd);
                fclose(fd);
                fd = NULL;
            }else{
                fprintf(stderr, "WSCAN: WARNING: Failed to create file: %s\n    The data were lost!\n", filename);
            }
            lc_stream_clean(&dconf);
            
            
            xi += xdir;
            // Will the motion put the axis out-of-range?
            if(xi<0 || xi>=xn){
                // Undo the index increment and jump out of the loop
                xi -= xdir;
                break;
            }
            // Command x-motion
            dconf.efch[XPULSE_EF].counts = xstep;
            lc_update_ef(&dconf);
            usleep(xwaitus);
        }
        // Each time a pass along the x-axis is complete, reverse the 
        // direction of motion.  Change the sign on xdir and update the
        // direction bit appropriately.
        xdir = -xdir;
        sprintf(stemp, "DIO%d", xdir_dioch);
        if(xdir>0)
            err = LJM_eWriteName(dconf.handle, stemp, XDIR_POS);
        else
            err = LJM_eWriteName(dconf.handle, stemp, !XDIR_POS);
            
        if(err){
            fprintf(stderr, "WSCAN: Failed to set x-direction pin while scanning!\n");
            lc_close(&dconf);
            return -1;
        }
        
        zi += zdir;
        // Will the motion put the axis out-of-range?
        if(zi<0 || zi>=zn){
            // Undo the index increment and jump out of the loop
            zi -= zdir;
            break;
        }
        // Command z-motion
        dconf.efch[ZPULSE_EF].counts = zstep;
        lc_update_ef(&dconf);
        usleep(zwaitus);
    }
    
    // Finally, calculate the steps to move back to the origin
    
    // Set the appropriate direction and move
    sprintf(stemp, "DIO%d", xdir_dioch);
    if(x0 >= xi){
        dconf.efch[XPULSE_EF].counts = (x0 - xi)*xstep;
        LJM_eWriteName(dconf.handle, stemp, XDIR_POS);
    }else{
        dconf.efch[XPULSE_EF].counts = (xi - x0)*xstep;
        LJM_eWriteName(dconf.handle, stemp, !XDIR_POS);
    }
    
    sprintf(stemp, "DIO%d", zdir_dioch);
    if(z0 >= zi){
        dconf.efch[ZPULSE_EF].counts = (z0 - zi)*zstep;
        LJM_eWriteName(dconf.handle, stemp, ZDIR_POS);
    }else{
        dconf.efch[ZPULSE_EF].counts = (zi - z0)*zstep;
        LJM_eWriteName(dconf.handle, stemp, !ZDIR_POS);
    }
    
    lc_update_ef(&dconf);
    
    lc_close(&dconf);
    return 0;
}


