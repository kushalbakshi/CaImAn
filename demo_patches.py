# -*- coding: utf-8 -*-
"""
Created on Wed Feb 24 18:39:45 2016

@author: agiovann
"""
#%%
import os
import ca_source_extraction as cse 
import calblitz as cb
import time
import psutil
import sys
import scipy
import pylab as pl
import numpy as np

%load_ext autoreload
%autoreload 2

n_processes = np.maximum(psutil.cpu_count() - 1,1) # roughly number of cores on your machine minus 1
print 'using ' + str(n_processes) + ' processes'
print "Restarting cluster to avoid unnencessary use of memory...."
sys.stdout.flush()  
cse.utilities.stop_server() 
cse.utilities.start_server(n_processes)
#%% slect all tiff files in current folder
fnames=[]
for file in os.listdir("./"):
    if file.endswith(".tif"):
        fnames.append(file)
fnames.sort()
print fnames  
fnames=fnames
#%% Create a unique file fot the whole dataset
# THIS IS  ONLY IF YOU NEED TO SELECT A SUBSET OF THE FIELD OF VIEW 
#fraction_downsample=.5;
#idx_x=slice(150,350,None)
#idx_y=slice(250,450,None)
#fname_new=cse.utilities.save_memmap(fnames,base_name='Yr',resize_fact=(1,1,fraction_downsample),remove_init=30,idx_xy=(idx_x,idx_y))
#%%  Create a unique file fot the whole dataset
fraction_downsample=1; # useful to downsample the movie across time. fraction_downsample=.1 measn downsampling by a factor of 10
fname_new=cse.utilities.save_memmap(fnames,base_name='Yr',resize_fact=(1,1,fraction_downsample))
#%%
Yr,d1,d2,T=cse.utilities.load_memmap(fname_new)
d,T=np.shape(Yr)
Y=np.reshape(Yr,(d1,d2,T),order='F') # 3D version of the movie
#%% build an image to check the presence of neurons
corr_image=1
if corr_image:
    # build correlation image
    Cn=cse.utilities.local_correlations(Y[:,:,:10000])
else:
    # build mean image
    Cn=np.mean(Y[:,:,:memory_fact*10000],axis=-1)
#%%
pl.imshow(Cn,vmax=1,cmap='gray')    
#%%
rf=9 # half-size of the patches in pixels. rf=25, patches are 50x50
stride = 2 #amounpl.it of overlap between the patches in pixels    
K=7 # number of neurons expected per patch
gSig=[4,4] # expected half size of neurons
merge_thresh=0.8 # merging threshold, max correlation allowed
p=0 #order of the autoregressive system
memory_fact=1; #unitless number accounting how much memory should be used. You will need to try different values to see which one would work the default is OK for a 16 GB system
save_results=False
#%%
options_patch = cse.utilities.CNMFSetParms(Y,p=0,gSig=gSig,K=K,ssub=1,tsub=4,thr=merge_thresh)
A_tot,C_tot,sn_tot, optional_outputs = cse.map_reduce.run_CNMF_patches(fname_new, (d1, d2, T), options_patch,rf=rf,stride = stride,
                                                                       n_processes=n_processes, backend='ipyparallel',memory_fact=memory_fact)
#%%
if save_results:
    np.savez('results_analysis_patch.npz',A_tot=A_tot.todense(), C_tot=C_tot, sn_tot=sn_tot,d1=d1,d2=d2)    

#%% if you have many components this might take long!
crd = cse.utilities.plot_contours(A_tot,Cn,thr=0.9)
#%% set parameters for full field of view analysis
options = cse.utilities.CNMFSetParms(Y,p=0,gSig=gSig,K=A_tot.shape[-1],thr=merge_thresh)
pix_proc=np.minimum(np.int((d1*d2)/n_processes/(T/2000.)),np.int((d1*d2)/n_processes)) # regulates the amount of memory used
options['spatial_params']['n_pixels_per_process']=pix_proc
options['temporal_params']['n_pixels_per_process']=pix_proc
#%% merge spatially overlaping and temporally correlated components      
A_m,C_m,nr_m,merged_ROIs,S_m,bl_m,c1_m,sn_m,g_m=cse.merge_components(Yr,A_tot,[],np.array(C_tot),[],np.array(C_tot),[],options['temporal_params'],options['spatial_params'],thr=options['merging']['thr'],mx=np.Inf)     
#%% display components  DO NOT RUN IF YOU HAVE TOO MANY COMPONENTS
crd = cse.utilities.plot_contours(A_m,Cn,thr=0.9)
#%% approximate the background temporal dynamics
pixels_bckgrnd=np.nonzero(A_m.sum(axis=-1)==0)[0]
f=np.sum(Yr[pixels_bckgrnd,:],axis=0)
print np.shape(pixels_bckgrnd)
#%% UPDATE SPATIAL OCMPONENTS
options['spatial_params']['backend']='ipyparallel' #parallelize with ipyparallel
t1 = time.time()
A2,b2,C2 = cse.spatial.update_spatial_components(Yr, C_m, f, A_m, sn=sn_tot, **options['spatial_params'])
print time.time() - t1
#%% UPDATE TEMPORAL COMPONENTS
options['temporal_params']['p']=p
C2,f2,S2,bl2,c12,neurons_sn2,g21,YrA = cse.temporal.update_temporal_components(Yr,A2,b2,C2,f,bl=None,c1=None,sn=None,g=None,**options['temporal_params'])
#%% Order components
#A_or, C_or, srt = cse.utilities.order_components(A2,C2)
#%% save analysis results in python and matlab format
if save_results:
    np.savez('results_analysis.npz',Cn=Cn,A_tot=A_tot.todense(), C_tot=C_tot, sn_tot=sn_tot, A2=A2.todense(),C2=C2,b2=b2,S2=S2,f2=f2,bl2=bl2,c12=c12, neurons_sn2=neurons_sn2, g21=g21,YrA=YrA,d1=d1,d2=d2)    
    scipy.io.savemat('output_analysis_matlab.mat',{'A_or':A_or,'C_or':C_or , 'YrA_or':YrA[srt,:], 'S_or': S2[srt,:] })
#%% stop server
cse.utilities.stop_server() 
#%%
quality_threshold=100
traces=C2+YrA
idx_components, fitness, erfc = cse.utilities.evaluate_components(traces,N=5,robust_std=True)
idx_components=idx_components[fitness>quality_threshold]

print(idx_components.size*1./traces.shape[0])
#%%
cse.utilities.view_patches_bar(Yr,scipy.sparse.coo_matrix(A2.tocsc()[:,idx_components]),C2[idx_components,:],b2,f2, d1,d2, YrA=YrA[idx_components,:])  
#%%
# select only portion of components
crd = cse.utilities.plot_contours(A2.tocsc()[:,idx_components],Cn,thr=0.9)