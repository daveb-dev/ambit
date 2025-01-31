#!/usr/bin/env python3

# Copyright (c) 2019-2022, Dr.-Ing. Marc Hirschvogel
# All rights reserved.

# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

import ufl

# fluid mechanics variational forms class
# Principle of Virtual Power
# TeX: \delta \mathcal{P} = \delta \mathcal{P}_{\mathrm{kin}} + \delta \mathcal{P}_{\mathrm{int}} - \delta \mathcal{P}_{\mathrm{ext}} = 0, \quad \forall \; \delta\boldsymbol{v}
class variationalform:
    
    def __init__(self, var_v, dv, var_p, dp, n=None):
        self.var_v = var_v
        self.var_p = var_p
        self.dv = dv
        self.dp = dp
        
        self.n = n
    
    ### Kinetic virtual power
    
    # TeX: \delta \mathcal{P}_{\mathrm{kin}} := \int\limits_{\Omega} \rho \left(\frac{\partial\boldsymbol{v}}{\partial t} + (\boldsymbol{\nabla}\otimes\boldsymbol{v})^{\mathrm{T}}\boldsymbol{v}\right) \cdot \delta\boldsymbol{v} \,\mathrm{d}v
    def deltaP_kin(self, a, v, rho, ddomain, v_old=None):
        
        if v_old is None:
            return rho*ufl.dot(a + ufl.grad(v) * v, self.var_v)*ddomain
        else:
            return rho*ufl.dot(a + ufl.grad(v) * v_old, self.var_v)*ddomain

    ### Internal virtual power

    # TeX: \delta \mathcal{P}_{\mathrm{int}} := \int\limits_{\Omega} \boldsymbol{\sigma} : \delta\boldsymbol{\gamma} \,\mathrm{d}v
    def deltaP_int(self, sig, ddomain):
        
        # TeX: \int\limits_{\Omega}\boldsymbol{\sigma} : \delta \boldsymbol{\gamma}\,\mathrm{d}v
        var_gamma = 0.5*(ufl.grad(self.var_v).T + ufl.grad(self.var_v))
        return ufl.inner(sig, var_gamma)*ddomain

    def deltaP_int_pres(self, v, ddomain):
        # TeX: \int\limits_{\Omega}\mathrm{div}\boldsymbol{v}\,\delta p\,\mathrm{d}v
        return ufl.div(v)*self.var_p*ddomain

    def residual_v_strong(self, a, v, rho, sig):
        
        return rho*(a + ufl.grad(v) * v) - ufl.div(sig)
    
    def residual_p_strong(self, v):
        
        return ufl.div(v)
    
    def f_inert(self, a, v, rho):
        
        return rho*(a + ufl.grad(v) * v)
    
    def f_viscous(self, sig):
        
        return ufl.div(dev(sig))

    ### External virtual power
    
    # Neumann load (Cauchy traction)
    # TeX: \int\limits_{\Gamma} \hat{\boldsymbol{t}} \cdot \delta\boldsymbol{v} \,\mathrm{d}a
    def deltaP_ext_neumann(self, func, dboundary):

        return ufl.dot(func, self.var_v)*dboundary
    
    # Neumann load in normal direction (Cauchy traction)
    # TeX: \int\limits_{\Gamma} p\,\boldsymbol{n}\cdot\delta\boldsymbol{v}\;\mathrm{d}a
    def deltaP_ext_neumann_normal(self, func, dboundary):

        return func*ufl.dot(self.n, self.var_v)*dboundary
    
    # Robin condition (dashpot)
    # TeX: \int\limits_{\Gamma} c\,\boldsymbol{v}\cdot\delta\boldsymbol{v}\;\mathrm{d}a
    def deltaP_ext_robin_dashpot(self, v, c, dboundary):

        return -c*(ufl.dot(v, self.var_v)*dboundary)
    
    # Robin condition (dashpot) in normal direction
    # TeX: \int\limits_{\Gamma} (\boldsymbol{n}\otimes \boldsymbol{n})\,c\,\boldsymbol{v}\cdot\delta\boldsymbol{v}\;\mathrm{d}a
    def deltaP_ext_robin_dashpot_normal(self, v, c_n, dboundary):

        return -c_n*(ufl.dot(v, self.n)*ufl.dot(self.n, self.var_v)*dboundary)



    ### Flux coupling conditions

    # flux
    # TeX: \int\limits_{\Gamma} \boldsymbol{n}\cdot\boldsymbol{v}\;\mathrm{d}a
    def flux(self, v, dboundary):
        
        return ufl.dot(self.n, v)*dboundary
        
    # surface - derivative of pressure load w.r.t. pressure
    # TeX: \int\limits_{\Gamma} \boldsymbol{n}\cdot\delta\boldsymbol{v}\;\mathrm{d}a
    def surface(self, dboundary):
        
        return ufl.dot(self.n, self.var_v)*dboundary
