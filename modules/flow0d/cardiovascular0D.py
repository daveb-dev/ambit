#!/usr/bin/env python3

# Copyright (c) 2019-2021, Dr.-Ing. Marc Hirschvogel
# All rights reserved.

# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import time
import sys, os, subprocess, time
import math
from pathlib import Path
import numpy as np
import sympy as sp

from mpiroutines import allgather_vec, allgather_vec_entry


class cardiovascular0Dbase:
    
    def __init__(self, theta, comm=None):
        self.T_cycl = 0 # duration of one cardiac cycle (gets overridden by derived syspul* classes)
        self.theta = theta # time-integration factor ]0;1]
        self.init = True # for output
        self.have_induced_pert = False
        if comm is not None: self.comm = comm # MPI communicator
    
    
    # evaluate model at current nonlinear iteration
    def evaluate(self, x, dt, t, df=None, f=None, K=None, c=[], a=None, fnc=[]):

        if isinstance(x, np.ndarray): x_sq = x
        else: x_sq = allgather_vec(x, self.comm)

        # rhs part df
        if df is not None:
            
            for i in range(self.numdof):
                df[i] = self.df__[i](x_sq, c, t, fnc)
            
        # rhs part f
        if f is not None:
            
            for i in range(self.numdof):
                f[i] = self.f__[i](x_sq, c, t, fnc)

        # stiffness matrix K
        if K is not None:
            
            for i in range(self.numdof):
                for j in range(self.numdof):
                    K[i,j] = self.Kdf__[i][j](x_sq, c, t, fnc) / dt + self.Kf__[i][j](x_sq, c, t, fnc) * self.theta

        # auxiliary variable vector a (for post-processing or periodic state check)
        if a is not None:
            
            for i in range(self.numdof):
                a[i] = self.a__[i](x_sq, c, t, fnc)


    # symbolic stiffness matrix contributions ddf_/dx, df_/dx
    def set_stiffness(self):
        
        for i in range(self.numdof):
            for j in range(self.numdof):
        
                self.Kdf_[i][j] = sp.diff(self.df_[i],self.x_[j])
                self.Kf_[i][j]  = sp.diff(self.f_[i],self.x_[j])


    # make Lambda functions out of symbolic Sympy expressions
    def lambdify_expressions(self):

        for i in range(self.numdof):
            self.df__[i] = sp.lambdify([self.x_, self.c_, self.t_, self.fnc_], self.df_[i], 'numpy')
            self.f__[i] = sp.lambdify([self.x_, self.c_, self.t_, self.fnc_], self.f_[i], 'numpy')
            self.a__[i] = sp.lambdify([self.x_, self.c_, self.t_, self.fnc_], self.a_[i], 'numpy')            
        
        for i in range(self.numdof):
            for j in range(self.numdof):
                self.Kdf__[i][j] = sp.lambdify([self.x_, self.c_, self.t_, self.fnc_], self.Kdf_[i][j], 'numpy')
                self.Kf__[i][j] = sp.lambdify([self.x_, self.c_, self.t_, self.fnc_], self.Kf_[i][j], 'numpy')


    # set prescribed variable values
    def set_prescribed_variables(self, x, r, K, val, index_prescribed):

        if isinstance(x, np.ndarray): xs, xe = 0, len(x)
        else: xs, xe = x.getOwnershipRange()

        # modification of rhs entry
        if index_prescribed in range(xs,xe):
            r[index_prescribed] = x[index_prescribed] - val

        # modification of stiffness matrix - all off-columns associated to index_prescribed = 0
        # diagonal entry associated to index_prescribed = 1
        for i in range(self.numdof):
            
            if i==index_prescribed:

                for j in range(self.numdof):
                
                    if j!=index_prescribed:
                        K[i,j] = 0.
                    else:
                        K[i,j] = 1.


    # time step update
    def update(self, var, df, f, var_old, df_old, f_old, aux, aux_old):

        if isinstance(var, np.ndarray): vs, ve = 0, len(var)
        else: vs, ve = var.getOwnershipRange()

        for i in range(vs,ve):
            
            var_old[i] = var[i]
            df_old[i]  = df[i]
            f_old[i]   = f[i]
            
            aux_old[i] = aux[i]
            
            
    # check for cardiac cycle periodcity 
    def cycle_check(self, var, varTc, varTc_old, t, cycle, cyclerr, eps_periodic, check='allvar', inioutpath=None, induce_pert_after_cycl=-1):
        
        if isinstance(varTc, np.ndarray): vs, ve = 0, len(varTc)
        else: vs, ve = var.getOwnershipRange()

        is_periodic = False
        
        if self.T_cycl > 0. and self.ModuloIsRelativeZero(t, self.T_cycl, t):
            
            for i in range(vs,ve):
                varTc[i] = var[i]
            
            is_periodic = self.check_periodic(varTc, varTc_old, eps_periodic, check, cyclerr)
            
            # definitely should not be True if we've not yet surpassed the "disease induction" cycle
            if cycle[0] <= induce_pert_after_cycl:
                is_periodic = False
            
            # write "periodic" initial conditions in case we want to restart from this model in another simulation
            if is_periodic and inioutpath is not None:
                self.write_initial(inioutpath, varTc_old, varTc)
            
            for i in range(vs,ve):
                varTc_old[i] = varTc[i]
                
            # update cycle counter
            cycle[0] += 1

        return is_periodic


    # some perturbations/diseases we want to simulate (mr: mitral regurgitation, ms: mitral stenosis, ar: aortic regurgitation, as: aortic stenosis)
    def induce_perturbation(self, perturb_type, cycle, induce_pert_after_cycl):
        
        if induce_pert_after_cycl > 0 and not self.have_induced_pert: # at least run through one healthy cycle
            
            if cycle > induce_pert_after_cycl:
                
                if self.comm.rank == 0:
                    print(">>> Induced cardiovascular disease type: %s" % (perturb_type))
                    sys.stdout.flush()
                
                if perturb_type=='mr': self.R_vin_l_max = 1.0e-5
                if perturb_type=='ms': self.R_vin_l_min = 2.5e-5
                if perturb_type=='ar': self.R_vout_l_max = 5.0e-5
                if perturb_type=='as': self.R_vout_l_min = 5.0e-5

                # arrays need re-initialization, expressions have to be re-set
                self.setup_arrays(), self.set_chamber_interfaces()
                self.equation_map(), self.set_stiffness(), self.lambdify_expressions()
                
                self.have_induced_pert = True

                
    # compare A to B
    def IsRelativeEqualTo(self, A, B, Ref):

        return (math.fabs(A-B)/Ref) < 1.0e-12


    # check of modulo is near zero
    def ModuloIsRelativeZero(self, value, modulo, Ref):

        return self.IsRelativeEqualTo(math.fmod(value+modulo/2.,modulo)-modulo/2.,0.0,Ref);

    
    # set pressure function for 3D FEM model (FEniCS)
    def set_pressure_fem(self, var, ids, pr0D, p0Da):
        
        # set pressure functions
        for i in range(len(ids)):
            pr0D.val = -allgather_vec_entry(var, ids[i], self.comm)
            p0Da[i].interpolate(pr0D.evaluate)


    # midpoint-averaging of state variables (for post-processing)
    def midpoint_avg(self, var, var_old, var_mid):
        
        if isinstance(var, np.ndarray): vs, ve = 0, len(var)
        else: vs, ve = var.getOwnershipRange()

        for i in range(vs,ve):
            var_mid[i] = self.theta*var[i] + (1.-self.theta)*var_old[i]


    # set up the dof, coupling quantity, rhs, and stiffness arrays
    def set_solve_arrays(self):

        self.x_, self.a_, self.a__ = [0]*self.numdof, [0]*self.numdof, [0]*self.numdof
        self.c_, self.fnc_ = [], []
        
        self.df_, self.f_, self.df__, self.f__ = [0]*self.numdof, [0]*self.numdof, [0]*self.numdof, [0]*self.numdof
        self.Kdf_,  self.Kf_  = [[0]*self.numdof for _ in range(self.numdof)], [[0]*self.numdof for _ in range(self.numdof)]
        self.Kdf__, self.Kf__ = [[0]*self.numdof for _ in range(self.numdof)], [[0]*self.numdof for _ in range(self.numdof)]


    # time-varying elastance
    def E_t(self, E_A, E_min, t, t0, act_dur):
        
        if t >= t0 and t <= t0 + act_dur:
            y = 0.5*(1.-np.cos(2.*np.pi*(t-t0)/act_dur))
        else:
            y = 0.0
        
        return E_A * y + E_min


    # prescribed elastance model 
    def E_p(self, erray, tarray, t):

        return np.interp(t, tarray, erray)


    # set chamber interfaces according to case and coupling quantity (can be volume, flux, or pressure)
    def set_chamber_interfaces(self):
        
        # loop over chambers
        i=0
        for ch in ['lv', 'rv', 'la', 'ra']:
            
            if self.chmodels[ch]=='prescr_elast':
                self.switch_V[i], self.switch_p[i] = 1, 0
                self.elastarrays[i], self.eqtimearray = self.set_prescribed_elastance(ch)
            
            elif self.chmodels[ch]=='0D_elast':
                self.switch_V[i], self.switch_p[i] = 1, 0
            
            elif self.chmodels[ch]=='3D_fem':
                if self.cq == 'volume':
                    self.v_ids.append(self.vindex_ch[i]) # variable indices for coupling
                    self.c_ids.append(self.cindex_ch[i]) # coupling quantity indices for coupling
                elif self.cq == 'flux':
                    self.switch_V[i], self.switch_p[i] = 0, 0
                    self.cname_prfx[i] = 'Q'
                    self.vname_prfx[i] = 'p'
                    self.v_ids.append(self.vindex_ch[i]) # variable indices for coupling
                    self.c_ids.append(self.cindex_ch[i]) # coupling quantity indices for coupling
                elif self.cq == 'pressure':
                    self.switch_V[i], self.switch_p[i] = 0, 1
                    self.cname_prfx[i] = 'p'
                    self.vname_prfx[i] = 'Q'
                    self.si[i] = 1 # switch indices of pressure / outflux
                    self.v_ids.append(self.vindex_ch[i]-self.si[i]) # variable indices for coupling
                    self.c_ids.append(i) # LMs: coupling quantity indices for coupling
                else:
                    raise NameError("Unknown coupling quantity!")
                
            else:
                raise NameError("Unknown chamber model for chamber %s!" % (ch))
            
            i+=1


    # set coupling state (populate x and c vectors with Sympy symbols) according to case and coupling quantity (can be volume, flux, or pressure)
    def set_coupling_state(self, ch, chvars, chfncs=[]):
        
        if ch == 'lv': V_unstressed, i = self.V_v_l_u,  0
        if ch == 'rv': V_unstressed, i = self.V_v_r_u,  1
        if ch == 'la': V_unstressed, i = self.V_at_l_u, 2
        if ch == 'ra': V_unstressed, i = self.V_at_r_u, 3
   
        # time-varying elastances
        if self.chmodels[ch]=='0D_elast' or self.chmodels[ch]=='prescr_elast':
            chvars[0] = chvars[1]/chfncs[0] + V_unstressed # V = p/E(t) + V_u
            chvars[2] = chvars[1] # downstream p is equal to p
            self.fnc_.append(chfncs[0])

        # 3D FEM model
        elif self.chmodels[ch]=='3D_fem': # also for 2D FEM models

            if self.chinterf[ch] == 1:
                
                chvars[2] = chvars[1] # downstream p is equal to p

                if self.cq == 'volume' or self.cq == 'flux':
                    self.c_.append(chvars[0]) # V or Q
                if self.cq == 'pressure':
                    self.x_[self.vindex_ch[i]-self.si[i]] = chvars[0] # Q
                    self.c_.append(chvars[1]) # p
                        
            elif self.chinterf[ch] == 2:
                
                if self.cq == 'volume' or self.cq == 'flux':
                    raise AttributeError("Chamber %s has more than 1 interface! Cannot use volume or flux coupling for this case!" % (ch))

                if self.cq == 'pressure':
                    self.x_[self.vindex_ch[i]-self.si[i]] = chvars[0] # Q
                    self.c_.append(chvars[1]) # p
                    self.c_.append(chvars[2]) # downstream p

            else:
                raise AttributeError("More than two 3D interfaces for chamber %s. Think of how to handle this!" % (ch))

        else:
            raise NameError("Unknown chamber model for chamber %s!" % (ch))

        return chvars


    # evaluate time-dependent state of chamber (for 0D elastance models)
    def evaluate_chamber_state(self, t):
        
        chamber_funcs=[]

        i=0
        for ch in self.chmodels:

            if self.chmodels[ch]=='0D_elast': # pay attention to different timings for atrial and ventricular activation!
                
                if ch == 'lv': E_max, E_min = self.E_v_max_l,  self.E_v_min_l
                if ch == 'rv': E_max, E_min = self.E_v_max_r,  self.E_v_min_r
                if ch == 'la': E_max, E_min = self.E_at_max_l, self.E_at_min_l
                if ch == 'ra': E_max, E_min = self.E_at_max_r, self.E_at_min_r
                
                if 'v' in ch: E_ch_t = self.E_t(E_max-E_min, E_min, t, 2.*(self.t_ed-0.), self.t_es-self.t_ed)
                if 'a' in ch: E_ch_t = self.E_t(E_max-E_min, E_min, t, 0., 2.*(self.t_ed-0.))
                
                chamber_funcs.append(E_ch_t)

            elif self.chmodels[ch]=='prescr_elast':
                
                E_ch_t = self.E_p(self.elastarrays[i], self.eqtimearray, t)
                
                chamber_funcs.append(E_ch_t)
                
            else:
                
                pass

            i+=1
            
        return chamber_funcs


    # initialize Lagrange multipliers for monolithic Lagrange-type coupling (FEniCS)
    def initialize_lm(self, var, iniparam):
        
        i = 0
        for ch in ['lv', 'rv', 'la', 'ra']:
            if self.chmodels[ch]=='3D_fem':
                
                if self.chinterf[ch] == 1: 
                
                    if ch=='lv':
                        if 'p_v_l_0' in iniparam.keys(): var[i] = iniparam['p_v_l_0']
                    if ch=='rv':
                        if 'p_v_r_0' in iniparam.keys(): var[i] = iniparam['p_v_r_0']
                    if ch=='la':
                        if 'p_at_l_0' in iniparam.keys(): var[i] = iniparam['p_at_l_0']
                    if ch=='ra':
                        if 'p_at_r_0' in iniparam.keys(): var[i] = iniparam['p_at_r_0']
                    i+=1
                
                # TODO: Check for multiple interfaces!
                else:
                    raise AttributeError("Check multiple interface LM initialization!")


    # set prescribed elastances (if we have p and V of a chamber over time i.e. from another simulation or measurements,
    # we set p_hat = p, V_hat = V and define the chamber's elastance as E = p_hat/V_hat)
    def set_prescribed_elastance(self, ch):
        
        if not self.have_elast:
            
            tmp = np.loadtxt(''+self.prescrpath+'/out/plot/raw/V_'+ch+'.txt')
            numdata = len(tmp)
            
            data = np.loadtxt(''+self.prescrpath+'/out/data_integral.txt', usecols=1)
            # cycle, no of steps per cycle and number of cycles (to reach periodcity) from data to be prescribed
            T_cycl_from_prescr = int(data[0])
            nstep_from_prescr = int(data[1])
            n_cycl_from_prescr = int(numdata/nstep_from_prescr)

            # computed chamber volumes for the cycle we want to prescribe
            vol_comp = np.loadtxt(''+self.prescrpath+'/out/plot/raw/V_'+ch+'.txt', skiprows=numdata-nstep_from_prescr, usecols=1)

            # computed chamber pressures for the cycle we want to prescribe
            pres_comp = np.loadtxt(''+self.prescrpath+'/out/plot/raw/p_'+ch+'.txt', skiprows=numdata-nstep_from_prescr, usecols=1)

            if ch == 'lv': V_unstressed = self.V_v_l_u
            if ch == 'rv': V_unstressed = self.V_v_r_u
            if ch == 'la': V_unstressed = self.V_at_l_u
            if ch == 'ra': V_unstressed = self.V_at_r_u

            # elastance wanted
            elast_array=np.zeros(len(vol_comp))
            for b in range(len(vol_comp)):
                elast_array[b] = pres_comp[b]/(vol_comp[b]-V_unstressed)
            
            # we have to interpolate the prescribed data onto an equidistant time array - in case the data had variable time steps!
            timedata_from_to_be_prescr = np.loadtxt(''+self.prescrpath+'/out/plot/raw/V_'+ch+'.txt', skiprows=numdata-nstep_from_prescr, usecols=0)
            
            # subtract time offset to have an array starting at t=0
            for b in range(len(timedata_from_to_be_prescr)):
                timedata_from_to_be_prescr[b] -= (n_cycl_from_prescr-1) * T_cycl_from_prescr
            
            # build an equidistant time array
            equidist_time_array = np.zeros(len(timedata_from_to_be_prescr))
            for b in range(len(timedata_from_to_be_prescr)):
                equidist_time_array[b] = (b+1)*self.T_cycl/len(timedata_from_to_be_prescr)

            # interpolate the data to the equidistant array
            elastinterp = np.interp(equidist_time_array, timedata_from_to_be_prescr, elast_array)
            
        else:
            
            elastinterp = np.loadtxt(''+self.prescrpath+'/elastances_'+ch+'.txt', skiprows=0)

            equidist_time_array = np.zeros(len(elastinterp))
            for i in range(len(equidist_time_array)):
                equidist_time_array[i] = (i+1)/len(equidist_time_array)
            
        return elastinterp, equidist_time_array


    # output routine for 0D models
    def write_output(self, path, t, var, aux):
        
        if isinstance(var, np.ndarray): var_sq = var
        else: var_sq = allgather_vec(var, self.comm)

        # mode: 'wt' generates new file, 'a' appends to existing one
        if self.init: mode = 'wt'
        else: mode = 'a'
        
        self.init = False

        if self.comm.rank == 0:

            for i in range(len(self.varmap)):
                
                filename = path+'/'+list(self.varmap.keys())[i]+'.txt'
                f = open(filename, mode)
                
                f.write('%.16E %.16E\n' % (t,var_sq[list(self.varmap.values())[i]]))
                
                f.close()

            for i in range(len(self.auxmap)):
                
                filename = path+'/'+list(self.auxmap.keys())[i]+'.txt'
                f = open(filename, mode)
                
                f.write('%.16E %.16E\n' % (t,aux[list(self.auxmap.values())[i]]))
                
                f.close()


    # to write initial conditions (i.e. after a model has reached periodcity, so we may want to export these if we want to use
    # them in a new simulation starting from a homeostatic state)
    def write_initial(self, path, varTc_old, varTc):
        
        if isinstance(varTc_old, np.ndarray): varTc_old_sq, varTc_sq = varTc_old, varTc
        else: varTc_old_sq, varTc_sq = allgather_vec(varTc_old, self.comm), allgather_vec(varTc, self.comm)
        
        if self.comm.rank == 0:
        
            filename1 = path+'/initial_data_Tstart.txt' # conditions at beginning of cycle
            f1 = open(filename1, 'wt')
            filename2 = path+'/initial_data_Tend.txt' # conditions at end of cycle
            f2 = open(filename2, 'wt')
            
            for i in range(len(self.varmap)):
                
                f1.write('%s %.16E\n' % (list(self.varmap.keys())[i]+'_0',varTc_old_sq[list(self.varmap.values())[i]]))
                f2.write('%s %.16E\n' % (list(self.varmap.keys())[i]+'_0',varTc_sq[list(self.varmap.values())[i]]))
                
            f1.close()
            f2.close()


    # if we want to set the initial conditions from a txt file
    def set_initial_from_file(self, initialdata):
    
        pini0D = {}
        with open(initialdata) as fh:
            for line in fh:
                (key, val) = line.split()
                pini0D[key] = float(val)
                
        return pini0D
