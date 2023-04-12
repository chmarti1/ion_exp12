#include "lconfig.h"
#include "wscan.h"
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
"   \"xdir\" (int): Which direction is positive (1 or 0).\n"\
"   \"xcal\" (float): The distance moved per step (>0).\n"\
"   \"xunits\" (str): The distance units string.\n"\
"   \"zstep\" (int): The z-axis increment in pulses (+/-).\n"\
"   \"zn\" (int): The number of z-axis scan locations (min 1).\n"\
"   \"zdir\" (int): Which direction is positive (1 or 0).\n"\
"   \"zcal\" (float): The distance moved per step (>0).\n"\
"   \"zunits\" (str): The distance units string.\n"\
"   These define a grid of disc locations in the x-z plane.  The x-axis\n"\
"   is assumed to have been carefully aligned with the plane of disc\n"\
"   rotation. The z-axis is roughly (but not necessarily precisely) \n"\
"   perpendicular to the plane of disc rotation.\n"\
" - There must be AT LEAST one meta parameter beginning with a lower case\n"\
"   'r', followed by an integer index, identifying a wire and its radius.\n"\
"   For example:\n"\
"       r0  16.4\n"\
"       r1  16.9\n"\
"   Defines a disc with two wires, each with the specified radius.\n"\
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
"(c)2023  Christopher R. Martin\n";


int main(int argc, char *argv[]){
    int ch,             // holds the character for the getopt system
        err;            // error index
    char config_filename[STR_LEN], 
        dest_directory[STR_LEN],
        slice_directory[STR_LEN],
        filename[STR_LEN],
        stemp[STR_SHORT],
        stemp1[STR_SHORT];
    AxisIterator_t xaxis, zaxis;
    double ftemp;
    int itemp, ii;
    
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
            printf("%s",help_text);
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

    // Initialize the axis iterators
    // This includes configuration
    if(ax_init(&xaxis, &dconf, 0, 'x')){
        fprintf(stderr, "WSCAN: Configuration of the x-axis failed.\n");
        return -1;
    }
    if(ax_init(&zaxis, &dconf, 1, 'z')){
        fprintf(stderr, "WSCAN: Configuration of the z-axis failed.\n");
        return -1;
    }
    // Verify that the wire radii are configured
    // wscan doesn't need them, but the post processing codes will
    for(ii=0; ii<LCONF_MAX_META; ii++){
        sprintf(stemp, "r%d", ii);
        if(lc_get_meta_type(&dconf, stemp) == LC_MT_FLT){
            lc_get_meta_flt(&dconf, stemp, &ftemp);
            printf("Wire %d radius: %lf", ii, ftemp);
        }else if(ii==0){
            fprintf(stderr, "WSCAN: Found no wire radii in the configuration file.\n");
            return -1;
        }else
            break;
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
    // If the directory already exists, warn the user
    }else{
        fprintf(stderr, "WSCAN: The destination directory already exists: %s\n", dest_directory);
        return -1;
    }

    // Set up the x- and z-axes iteration
    ax_iter_start(&zaxis);
    ax_iter_start(&xaxis);
    // z-loop
    while(!(err = ax_iter(&zaxis, -1))){
        // Let the user know what's goin on
        printf("z-index: %3d of %3d  (%lf%s)\n", 
                ax_get_index(&zaxis), 
                zaxis.niter, 
                ax_get_pos(&zaxis), 
                zaxis.units);
        
        // Create a directory for each z-slice
        sprintf(slice_directory, "%s/%03d", dest_directory, ax_get_index(&zaxis));
        if(mkdir(slice_directory, 0755)){
            fprintf(stderr, "WSCAN: Failed to create slice directory: %s\n", slice_directory);
            lc_close(&dconf);
            return -1;
        }
        
        // x-loop
        while(!(err = ax_iter(&xaxis, -1))){
            // Let the user know what's going on
            printf("  x-index: %3d of %3d  (%lf%s)\n", 
                    ax_get_index(&xaxis), 
                    xaxis.niter, 
                    ax_get_pos(&xaxis), 
                    xaxis.units);
            // Record the current z and x indices
            if( lc_put_meta_flt(&dconf, "x", ax_get_pos(&xaxis)) || 
                    lc_put_meta_flt(&dconf, "y", 0.) ||
                    lc_put_meta_flt(&dconf, "z", ax_get_pos(&zaxis)) ){
                fprintf(stderr, "WSCAN: WARNING! Failed to write the (x,y,z) meta values prior to data acquisition\n");
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
            sprintf(filename, "%s/%03d_%03d.dat", 
                    slice_directory, 
                    ax_get_index(&zaxis), 
                    ax_get_index(&xaxis));
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
            
        }// End x-loop
        
        // Set up for the next scan
        ax_iter_repeat(&xaxis);
    }// End z-loop
    
    // Move back to the origin
    printf("Returning to home.\n");
    // X-axis first
    ax_move(&xaxis, -xaxis.state, -1);
    // Then the z-axis
    ax_move(&zaxis, -zaxis.state, -1);
    
    // All done
    lc_close(&dconf);
    return 0;
}


