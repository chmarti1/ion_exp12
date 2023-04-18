#include "lconfig.h"
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
        default:
            fprintf(stderr, "MOVE: Unrecognized option: %c\n", ch);
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
    if(1 != sscanf(argv[argc-1], &distance)){
        fprintf(stderr, "MOVE: The distance must be a number. Use -h for more info.\n");
        return -1;
    }
    
    //
    // Load the configuration file
    //
    if(lc_load_config(&dconf, 1, config){
        fprintf(stderr, "MOVE: Failed to load the configuration file: %s\n", config);
        return -1;
    }
    
    //
    // Configure the axis motion
    //
    if(ax_init(&ax, &dconf, efch, axis)){
        fprintf(stderr, "MOVE: Failed while initializing the axis for motion.\n");
        return -1;
    }
    //
    // Execute the motion
    //
    if(ax_move(&ax, (int) (distance/ax->cal), wait)){
        fprintf(stderr, "MOVE: Error during motion!\n");
        return -1;
    }
    
    //
    // All done
    //
    return 0;
}
