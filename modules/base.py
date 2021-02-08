#!/usr/bin/env python3

# Copyright (c) 2019-2021, Dr.-Ing. Marc Hirschvogel
# All rights reserved.

# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

class problem_base():
    
    def __init__(self, io_params, time_params, comm):
        
        self.comm = comm
        
        self.problem_type = io_params['problem_type']

        self.timint = time_params['timint']
        
        if 'maxtime' in time_params.keys(): self.maxtime = time_params['maxtime']
        if 'numstep' in time_params.keys(): self.numstep = time_params['numstep']
        if 'numstep_stop' in time_params.keys(): self.numstep_stop = time_params['numstep_stop']

        if 'maxtime' in time_params.keys(): self.dt = self.maxtime/self.numstep
