#!/usr/bin/python3
"""Langmuir probe spatial measurement utilities

*** AS A COMMAND LINE UTILITY ***
The wire.py file can be used as a commandline utility.  It accepts the
format:
    $ wire.py [options] <command> ...
    
Commands recognized by wire.py are:
    stat    Collect and display statistics from a wire data file
    view    Produce a pseudocolor image from a wire coefficient file

# Print help and exit
    $ wire.py -h
    $ wire.py -h <command>

# Collect statistics on the wire file
    $ wire.py [options] stat <wiredatafile> <target>
    
# Construct a view of the output of wsolve
    $ wire.py [options] view <wsolvefile> <target>
    
*** AS A PYTHON MODULE ***
If imported as a Python module, wire provides two classes that can be used
for analyzing the wire data files and the wsolve output data:
  
  WireData
    The WireData class interacts with a wire data file.  It can be used
    to read or write these files.
    
  WireCoefficients
    The WireCoefficients class loads the complex coefficients that are output by
    wsolve.  A class instance can be used to evaluate the solution at 
    arbitrary points in the domain, generate plots, or recall the raw
    coefficients.
    
For more information call the inline help for each of these classes.

(c)2023 Christopher Martin
"""

import numpy as np
import array,struct
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import sys
from getopt import getopt



help_text = {
    'stat':"""$ wire.py [-c config] [-qp] stat <wiredata> <outfile>

Collect statistics on the data in the WireData using wsolve's configuration
file.  Generates a png with the name given in <outfile> with a 2D histogram
and a point cloud showing the wire tip locations in the x,y plane.  The
histogram shows the number of wire tip instances in each of a grid of bins
in the x,y plane.  The Lx,Ly domain is shown in both plots with a red box.

These plots are useful for tuning the configuration parameters to avoid a
poorly tuned numerical problem in wsolve.  When the parameters are optimal,
nearly all of the bins inside the domain will contain one wire tip, and 
none of the bins will contain zero wire tips.  Because these plots are 
substantially faster to generate than the wsolve matrix, it becomes possible
to iterate until ideal parameters are found.

Statistics included in the image are:
  File - the wire data file analyzed
  Ndata - the number of data points in the file
  Configfile - the configuration file read to determine Nx,Ny,Lx, and Ly
  Nx,Ny - number of wavenumbers to use in the model
  Lx,Ly - domain size
  shift - x,y shift to apply to all wire data
  xbins,ybins
    The x- and y-axis are divided into bins for the histogram. The x- and
    y-bins parameters are the index range used in the histogram
  x-binsize,y-binsize
    The x- and y-axis binsize are calculated as Lx/(2 Nx) and Ly/(2 Ny)
  Domain:
    bins: number of bins contained in the Lx,Ly domain
    zero bins: number of bins in the domain with no wire tips (this is bad)
    Nmin, Nmax, Nmean
      minimum, maximum, and mean number of wire tip points contained in bins
      inside the domain.

It should be emphasized that when the wire pass all the way through the 
domain, its tip will lie outside the domain.  These cases will provide 
additional data for the solution, but 

-p      Pretty Plot
  Do not add statistics text to the plot

-q      Run Quietly
  In quiet mode, statistics are not printed to stdout
""",
    'view':"""$ wire.py [-qp] view <wsolveoutput> <outfile>
        
The view command is used to load a wsolve output file and generate a pseudo-
color plot of local current density throughout the x,y domain.  The output
is written to <outfile> as a png.

-p      Pretty Plot
  Do not add text to the image.
  
-q      Run Quietly
  Do not print to standard output
"""
}


class WireData:
    """The WireData class is a wrapper for interacting with raw wire data

The WireData binary files are inputs to the WSOLVE executable.  They are
entries with double precision floating point data groups,

    radius, x, y, angle, current
    
Each "data point" is one of these groups of five double precision floats
that specifies the radius of the wire (allowing multiple wires), the x,y
location of the disc center, the wire angle in radians, and the wire 
current.
"""
    
    def __init__(self, filename):
        self.filename = filename
        self.fd = None
        self.isread = False
        self.lineformat = '@ddddd'
        self.linebytes = struct.calcsize(self.lineformat)

    def open(self, mode):
        if self.fd is not None:
            raise FileExistsError('File is already open.')
        if mode in ['r', 'rb']:
            self.fd = open(self.filename, 'rb')
            self.isread = True
        elif mode in ['w', 'wb']:
            self.fd = open(self.filename, 'wb')
            self.isread = False
        elif mode in ['a', 'ab']:
            self.fd = open(self.filename, 'ab')
            self.isread = False
        elif mode in ['x', 'xb']:
            self.fd = open(self.filename, 'xb')
            self.isread = False
        return self
    
    def close(self):
        if self.fd is None:
            raise FileExistsError('File is already closed.')
        self.fd.close()
        self.fd = None
        self.isread = False
        
    def __enter__(self):
        return self
        
    def __iter__(self):
        if not self.isread:
            raise Exception('The file is not opened in read mode.')
        return self
    
    def __next__(self):
        bb = self.fd.read(self.linebytes)
        if len(bb) < self.linebytes:
            raise StopIteration
        return struct.unpack(self.lineformat, bb)
        
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.fd is not None:
            self.fd.close()
            self.fd = None
            self.isread = False
        return False

    def readline(self):
        """Read and return a four-element tuple
    (R, X, Y, theta, I) = wf.readline()

R is the wire radius
X,Y is the disc center location
theta is the wire angle (in radians) relative to the x-axis
I is the measured wire current

Returns an empty tuple if end-of-file
"""
        if self.isread:
            bb = self.fd.read(self.linebytes)
            if len(bb) < self.linebytes:
                return ()
            return struct.unpack(self.lineformat, bb)
        raise Exception('The file is not opened in read mode.')
        
    def writeline(self, r, x, y, theta, I):
        """Write a single radius, diameter, angle, and current entry to the file
        
    with wf.open('w'):
        wf.writeline(r,d,theta,I)
"""
        if self.isread or self.fd is None:
            raise Exception('The file is not opened in write mode.')
        self.fd.write(struct.pack(self.lineformat, r,x,y,theta,I))
        
    def read(self):
        """Read all data from the file
    r,d,theta,I = wf.read()
    
Reads in numpy arrays of radius, distance, angle, and current.
"""
        if not self.isread or self.fd is None:
            raise Exception('The file is not opened in read mode.')
        R = []
        X = []
        Y = []
        T = []
        I = []
        for r,x,y,t,i in self:
            R.append(r)
            X.append(x)
            Y.append(y)
            T.append(t)
            I.append(i)
        return np.array(R), np.array(X), np.array(Y), np.array(T), np.array(I)
            
        

class WireCoefficients:
    """WireCoefficients - load and interpret the output of wsolve
    
    wc = WireCoefficients('filename.wc')

Once loaded, the WireCoefficients instance contains the configuration 
settings that were used to calculate the coefficients.  The Nx, Ny, Lx,
and Ly parameters are all stored in two-element arrays
    [Nx, Ny] = wc.N
    [Lx, Ly] = wc.L

The total number of coefficients is also available
    ncoef = wc.ncoef

The coefficients are available by their m,n index
    Cmn = wc[m,n]
    
or by in sequential order (this is probably less useful)
    Ci = wc[index]
    
The WireCoefficients instance can be queried for ion current density
like a function, using x,y coordinates (with array support) within the 
domain
    I = wc(x,y)

Finally, a pseudocolor image of ion current density everywhere in the
domain can be produced using the show() method.  See the show() 
documentation for more information.
"""
    def __init__(self, filename):
        self.N = None
        self.L = None
        self.C = None
        self.C_mn = None
        self.I0 = None
        self.nu = None
        self.nu_mn = None
        self.ncoef = 0
        self.filename = filename
        
        with open(filename,'rb') as ff:
            raw = ff.read(struct.calcsize('II'))
            self.N = np.array(struct.unpack('II',raw), dtype=int)
            raw = ff.read(struct.calcsize('dd'))
            self.L = np.array(struct.unpack('dd', raw), dtype=float)
            self.ncoef = np.prod(2*self.N+1)
            raw = ff.read(2 * (self.ncoef+1) * struct.calcsize('d'))
            raw = array.array('d', raw)
            nn = len(raw)
            if nn//2 != self.ncoef+1:
                raise Exception(f'WireCoefficients: Coefficient dimension missmatch; NCOEF: {self.ncoef} NREAD: {nn//2}')
            nn -= 2
            self.C = np.array(raw[0:nn:2]) + 1j*np.array(raw[1:nn:2])
            self.I0 = raw[nn]
        
        # Initialize the nu arrays
        self.nu_mn = np.meshgrid(
                np.arange(-self.N[0], self.N[0]+1)/self.L[0],
                np.arange(-self.N[1], self.N[1]+1)/self.L[1])
        self.nu = [this.reshape((self.ncoef,)) for this in self.nu_mn]

    
    def __call__(self, x, y):
        x,y = np.broadcast_arrays(x,y)
        zshape = x.shape
        x,y = x.reshape((x.size,1)),y.reshape((y.size,1));
        
        nux = self.nu[0].reshape((1,self.ncoef))
        nuy = self.nu[1].reshape((1,self.ncoef))
        
        z = np.dot( np.exp(2j*np.pi*(nux*x + nuy*y)), self.C).real
        
        return z.reshape(zshape)
        
    def __getitem__(self, key):
        if isinstance(key,tuple):
            return self.C[self.mn_to_index(*key)]
        else:
            return self.C[key]
            
    def mn_to_index(self, m, n):
        """Calculate the serial index corresponding to m,n
    index = SD.mn_to_index(m,n)
"""        
        if abs(m) > self.N[0]:
            raise KeyError(f'WireCoefficients[m,n] index is out of range: m={m}; Nx={self.N[0]}')
        elif abs(n) > self.N[1]:
            raise KeyError(f'WireCoefficients[m,n] index is out of range: n={n}; Ny={self.N[1]}')
        return (m+self.N[0]) + (n+self.N[1])*(2*self.N[0]+1)

    def index_to_mn(self, index):
        """Calculate the m,n integers from the serial index
    m,n = SD.mn_to_index(index)
"""        
        if index<0 or index >= self.ncoef:
            raise KeyError(f'WireCoefficients[index] index is out of range: index={index}; ncoef={self.ncoef}')
        n,m = divmod(index, 2*self.N[0]+1)
        return m-self.N[0], n-self.N[1]
        
    def grid(self,Nx=None, Ny=None):
        """GRID - evaluate the solution at grid points
    x,y,I = grid()
        OR
    x,y,I = grid(N)
        Or
    x,y,I = grid(Nx, Ny)
    
If no argument is given, the grid spacing is selected automatically 
based on the highest wave number in each axis.  If a single scalar 
argument is given, it is treated as the number of grid oints in each
axis.  If tuple pair of arguments are found, they are interpreted as 
the number of grid points in the x- and y-axes.
"""
        # If no arguments are given
        if Nx is None:
            if Ny is None:
                Nx,Ny = 4*self.N+2
            else:
                raise Exception('Cannot specify Ny without specifying Nx.')
        # If Nx is given
        elif Ny is None:
            Ny = Nx
        # If Nx and Ny are given, do nothing        
        x = np.linspace(-self.L[0]/2,self.L[0]/2,2*Nx+1)
        y = np.linspace(-self.L[1]/2, self.L[1]/2, 2*Ny+1)
        x,y = np.meshgrid(x,y)
        return x,y

    def show(self, x, y, ax=None, block=True):
        
        # If the axes are not specified, create a new figure and a new
        # axes.
        if ax is None:
            fig,ax = plt.subplots(1,1)
        # If the axes are specified, grab the parent figure
        else:
            fig = ax.get_figure()
        
        ax.pcolor(x,y,self(x,y), shading='auto')
        ax.set_aspect(self.L[1] / self.L[0])
        ax.set_xlim([-self.L[0]/2, self.L[0]/2])
        ax.set_ylim([-self.L[1]/2, self.L[1]/2])
        if block:
            plt.show()

if __name__ == '__main__':
    opts,args = getopt(sys.argv[1:], 'pqc:h')
    configfile = 'wsolve.conf'
    verbose = True
    pretty = False
    config = {}
    
    # Scan the options
    for oo  in opts:
        if oo[0] == '-h':
            if len(args) == 0:
                print(__doc__)
                exit(0)
            elif args[0] in help_text:
                print(help_text[args[0]])
                exit(0) 
            else:
                print("Unrecognized command: " + args[0])
                print(__doc__)
                exit(0)
        elif oo[0] == '-c':
            configfile = oo[1]
        elif oo[0] == '-q':
            verbose = False
        elif oo[0] == '-p':
            pretty = True
        else:
            raise Exception('Unrecognized option: ' + oo[0])
    
    # Identify the command
    cmd = args[0].lower()
    
    # Case out the commands
    if cmd == 'stat':
        if len(args)!=3:
            print(help_text['hist'])
            raise Exception('After command "hist" two arguments are expected.')
            
        infile = args[1]
        target = args[2]
        ##
        ## Read in the configuration file
        ##
        params = [('nthread', int), 
                ('Nx', int), ('Ny', int), 
                ('Lx', float), ('Ly', float),
                ('xshift', float),
                ('yshift', float)]
                
        with open(configfile,'r') as fd:
            words = fd.read().split()
        
        for pstr, ptype in params:
            pfound = words.pop(0)
            if pfound != pstr:
                raise Exception('Configuration syntax error in ' + configfile + '. Expected: ' + pstr + ' Found: ' + pfound)
            try:
                config[pstr] = ptype(words.pop(0))
            except:
                raise Exception('Configuration syntax error in ' + configfile + '. Failed while parsing: ' + pstr)
        

        # Read in the data
        with WireData(infile).open('r') as wf:
            r,x,y,theta,I = wf.read()
        # Apply the configured shift
        x += config['xshift']
        y += config['yshift']
        # Move the coordinates to the wire tip
        x += r*np.cos(theta)
        y += r*np.sin(theta)
        # Calculate the histogram bin sizes
        xbin = config['Lx']/(2*config['Nx'])
        ybin = config['Ly']/(2*config['Ny'])
        # Calculate coordinate bin indices
        xi = np.array(np.floor(x / xbin), dtype=int)
        yi = np.array(np.floor(y / ybin), dtype=int)
        # Find the maximum and minimum limits
        xi_min = np.min(xi)
        xi_max = np.max(xi)
        nx = xi_max - xi_min + 1
        
        yi_min = np.min(yi)
        yi_max = np.max(yi)
        ny = yi_max - yi_min + 1
        
        count = np.zeros((ny,nx), dtype=int)
        
        for xii,yii in zip(xi,yi):
            count[yii-yi_min,xii-xi_min] += 1
        
        xx = np.arange(xi_min,xi_max+2)*xbin
        yy = np.arange(yi_min,yi_max+2)*ybin
        xx,yy = np.meshgrid(xx,yy)
        fig,ax = plt.subplots(1,2,figsize=(12,6),sharey=True)
        
        pc = ax[0].pcolor(xx,yy,count,shading='flat',cmap='Greys')
        ax[0].set_aspect(1.0)
        fig.colorbar(pc,ax=ax[0])
        Lx = config['Lx']/2
        Ly = config['Ly']/2
        ax[0].add_patch(Polygon([[-Lx,-Ly],[-Lx,Ly],[Lx,Ly],[Lx,-Ly]],\
                facecolor='none', edgecolor='r'))
                
        ax[1].plot(x,y,'k,')
        ax[1].add_patch(Polygon([[-Lx,-Ly],[-Lx,Ly],[Lx,Ly],[Lx,-Ly]],\
                facecolor='none', edgecolor='r'))
        ax[1].set_aspect(1.0)
        
        N = len(r)
        Id = np.abs(xx[:-1,:-1]) <= 0.5*config['Lx']
        Id = np.logical_and(Id, np.abs(yy[:-1,:-1]) <= 0.5*config['Ly'])
        Nbins = np.sum(Id)
        Nzero = np.sum(count[Id]==0)
        Nmin = np.min(count[Id])
        Nmax = np.max(count[Id])
        Nmean = np.mean(count[Id])

        if not pretty:
            info = f'File:{infile}  Ndata:{N}\n'
            info += f'Config:{configfile}  Nx:{config["Nx"]}  Ny:{config["Ny"]}  Lx:{config["Lx"]}  Ly:{config["Ly"]}  shift:{config["xshift"]},{config["yshift"]}'
            fig.text(0.25,0.95,info,ha='center',va='center')
            info = f'xbins:[{xi_min}, {xi_max}]  x-binsize: {xbin:.4f}  ybins:[{yi_min}, {yi_max}]  y-binsize: {ybin:.4f}\n'
            info += f'Domain: bins:{Nbins}  zero bins:{Nzero}  Nmin:{Nmin}  Nmax:{Nmax}  Nmean:{Nmean:.2f}'
            fig.text(0.75, 0.95, info, ha='center', va='center')
            
        if not target.endswith('.png'):
            target = target + '.png'
        
        fig.savefig(target)
        
        if verbose:
            print(f'File:{infile}')
            print(f'{N} data points')
            print(f'Config:{configfile}')
            print(f'  Nx:{config["Nx"]}')
            print(f'  Ny:{config["Ny"]}')
            print(f'  Lx:{config["Lx"]}')
            print(f'  Ly:{config["Ly"]}')
            print(f'Grid...')
            print(f'  x:[{xi_min}, {xi_max}]  bin: {xbin}')
            print(f'  y:[{yi_min}, {yi_max}]  bin: {ybin}')
            print(f'Domain...')
            print(f'  {Nzero} of {Nbins} bins with no data')
            print(f'  {Nmin} minimum data')
            print(f'  {Nmax} maximum data')
            print(f'  {Nmean} mean data per bin')
        
    elif cmd == 'view':
        if len(args)!=3:
            print(help_text['view'])
            raise Exception('After command "view" two arguments are expected.')
            
        infile = args[1]
        target = args[2]
        
        sd = WireCoefficients(infile)
        x,y = sd.grid()
        
        fig,ax = plt.subplots(1,1,figsize=(6,6))
        sd.show(x,y,ax=ax,block=False)
        
        if pretty:
            ax.set_xticks([])
            ax.set_yticks([])
            fig.tight_layout()
        else:
            info = f'File: {infile}\nNx:{sd.N[0]}  Ny:{sd.N[1]}  Lx:{sd.L[0]}  Ly:{sd.L[1]}' 
            fig.text(0.5,0.95,info, ha='center', va='center')
            # Set up a grid with intelligent ticks
            xticks = np.linspace(-sd.L[0]/2,sd.L[0]/2,5)
            yticks = np.linspace(-sd.L[1]/2, sd.L[1]/2,5)
            ax.set_xticks(xticks)
            ax.set_yticks(yticks)
            xx,yy = np.meshgrid(xticks,yticks)
            ax.plot(xx,yy,linestyle='none',marker='+',mec='k',ms=12)
        
        if not target.endswith('.png'):
            target = target + '.png'
        fig.savefig(target)
        
    else:
        raise Exception('Unrecognized command: ' + args[0])
