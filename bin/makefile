lconfig.o: lconfig.c lconfig.h lcmap.h
	gcc -Wall -c lconfig.c -o lconfig.o

lcmap.o: lcmap.c lcmap.h
	gcc -Wall -c lcmap.c -o lcmap.o

wscan: wscan.c lcmap.o lconfig.o
	gcc -Wall wscan.c lconfig.o lcmap.o -lm -lLabJackM -o wscan
