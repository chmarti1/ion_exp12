#include "lconfig.h"
#include "wscan.h"
#include <stdio.h>
#include <unistd.h>
#include <string.h>


const char config_default[] = "wscan.conf";

const char help_text[] = \
"move <options> <axis> <distance>\n"\
"\n"\
"Move an x,y,z stepper motor-driven translation stage a specified\n"\
"distance along the specified axis. The axis must be a single character\n"\
"specifying x-, y-, or z-axis motion.  Options are listed below.\n"\
"\n"\
"To allow negative distances, use the underscore (\"_\") character instead\n"\
"of a hyphen for the negative sign.  For example, to move -10 mm,\n"
"    $ move x _10\n"
"\n"\
"The move binary uses the same \"wscan.conf\" configuration file used by\n"\
"the wscan binary to define axis motion and calibration. See \"wscan -h\"\n"\
"for more information.\n"\
"\n"\
"-c <configfile>\n"\
"  Override the default configuration file: \"wscan.conf\".\n"\
"-e\n"\
"  Exit quickly. By default, the program calculates the time required for\n"\
"  the motion to complete and waits appropriately. With the -e option set,\n"\
"  the appropriate number of pulses are sent and the binary exits\n"\
"  immediately\n"\
"\n"\
"-h\n"\
"  Display this help text and exit immediately.\n"\
"\n"\
"(c)2023 Christopher R. Martin\n";


int main(int argc, char *argv[]){
    char ch, axis;
    int wait = -1;
    double distance = 0;
    char *config = (char *) config_default;
    char *distance_s;
    int distance_i;
    int efch;
    lc_devconf_t dconf;
    AxisIterator_t ax;
    
    // Parse command-line options
    while((ch = getopt(argc, argv, "hec:")) >= 0){
        switch(ch){
        case 'h':
            printf("%s",help_text);
            return 0;
        case 'e':
            wait = 0;
            break;
        case 'c':
            config = optarg;
            break;
        // If the option is unrecognized, let optarg raise the error
        default:
            return -1;
        }
    }
    
    //
    // Parse the non-option arguments - two are required
    //
    if(argc - optind != 2){
        fprintf(stderr, "MOVE: Two non-option arguments required. Use -h for more info.\n");
        return -1;
    }
    
    //
    // First, parse the axis
    //
    if(strlen(argv[argc-2]) != 1){
        fprintf(stderr, "MOVE: The axis must be a single character.\n");
        return -1;
    }
    axis = argv[argc-2][0];
    // Check the axis
    if(axis == 'x' || axis == 'X'){
        axis = 'x';
        efch = 0;
    }else if(axis == 'y' || axis == 'Y'){
        axis = 'y';
        fprintf(stderr, "MOVE: y-axis motion is not currently supported.\n");
        return -1;
    }else if(axis == 'z' || axis == 'Z'){
        axis = 'z';
        efch = 1;
    }else{
        fprintf(stderr, "MOVE: The axis must be 'x', 'y', or 'z'.\n");
        return -1;
    }
    
    //
    // Parse the distance
    //
    distance_s = argv[argc-1];
    if(distance_s[0] == '_')
        distance_s[0] = '-';
    
    if(1 != sscanf(distance_s, "%lf", &distance)){
        fprintf(stderr, "MOVE: The distance must be a number. Use -h for more info.\n");
        return -1;
    }
        
    //
    // Load the configuration file
    //
    if(lc_load_config(&dconf, 1, config)){
        fprintf(stderr, "MOVE: Failed to load the configuration file: %s\n", config);
        return -1;
    }
    if(lc_open(&dconf)){
        fprintf(stderr, "MOVE: Failed to connect to the LabJack.\n");
        return -1;
    }
    if(lc_upload_config(&dconf)){
        fprintf(stderr, "MOVE: Failed to upload the configuration.\n");
        lc_close(&dconf);
        return -1;
    }
    
    //
    // Configure the axis motion
    //
    if(ax_init(&ax, &dconf, efch, axis)){
        fprintf(stderr, "MOVE: Failed while initializing the axis for motion.\n");
        lc_close(&dconf);
        return -1;
    }
    
    // Calculate the motion parameters and tell the user
    distance_i = (int) distance / ax.cal;
    printf("  %c %+f0.3%s (%+d)\n", axis, distance, ax.units, distance_i);
    
    //
    // Execute the motion
    //
    if(ax_move(&ax,distance_i, wait)){
        fprintf(stderr, "MOVE: Error during motion!\n");
        lc_close(&dconf);
        return -1;
    }
    
    //
    // All done
    //
    lc_close(&dconf);
    return 0;
}
