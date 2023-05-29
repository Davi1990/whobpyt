"""
Authors: Zheng Wang, John Griffiths, Andrew Clappison, Hussain Ather
Neural Mass Model fitting
module for wong-wang model
"""

import torch
from torch.nn.parameter import Parameter
from whobpyt.datatypes.parameter import par
from whobpyt.models.RWW.ParamsRWW import ParamsRWW
from whobpyt.datatypes.AbstractParams import AbstractParams
from whobpyt.datatypes.AbstractNMM import AbstractNMM
import numpy as np  # for numerical operations

class RNNRWW(AbstractNMM):
    """
    A module for forward model (WWD) to simulate a window of BOLD signals
    Attibutes
    ---------
    state_size : int
        the number of states in the WWD model
    input_size : int
        the number of states with noise as input
    tr : float
        tr of fMRI image
    step_size: float
        Integration step for forward model
    steps_per_TR: int
        the number of step_size in a tr
    TRs_per_window: int
        the number of BOLD signals to simulate
    node_size: int
        the number of ROIs
    sc: float node_size x node_size array
        structural connectivity
    fit_gains: bool
        flag for fitting gains 1: fit 0: not fit
    g, g_EE, gIE, gEI: tensor with gradient on
        model parameters to be fit
    gains_con: tensor with node_size x node_size (grad on depends on fit_gains)
        connection gains exp(gains_con)*sc
    std_in std_out: tensor with gradient on
        std for state noise and output noise
    g_m g_v f_EE_m g_EE_v sup_ca sup_cb sup_cc: tensor with gradient on
        hyper parameters for prior distribution of g gEE gIE and gEI
    Methods
    -------
    forward(input, external, hx, hE)
        forward model (WWD) for generating a number of BOLD signals with current model parameters
    """
    use_fit_lfm = False
    input_size = 2

    def __init__(self, node_size: int,
                 TRs_per_window: int, step_size: float, sampling_size: float, tr: float, sc: float, use_fit_gains: bool,
                 param: ParamsRWW, use_Bifurcation=True, use_Gaussian_EI=False, use_Laplacian=True,
                 use_dynamic_boundary=True) -> None:
        """
        Parameters
        ----------

        tr : float
            tr of fMRI image
        step_size: float
            Integration step for forward model
        TRs_per_window: int
            the number of BOLD signals to simulate
        node_size: int
            the number of ROIs
        sc: float node_size x node_size array
            structural connectivity
        use_fit_gains: bool
            flag for fitting gains 1: fit 0: not fit
        use_Laplacian: bool
            using Laplacian or not
        param: ParamsModel
            define model parameters(var:0 constant var:non-zero Parameter)
        """
        super(RNNRWW, self).__init__()
        
        self.state_names = ['E', 'I', 'x', 'f', 'v', 'q']
        self.output_names = ["bold"]
        self.model_name = "RWW"
        
        self.state_size = 6  # 6 states WWD model
        # self.input_size = input_size  # 1 or 2
        self.tr = tr  # tr fMRI image
        self.step_size = step_size  # integration step 0.05
        self.steps_per_TR = int(tr / step_size)
        self.TRs_per_window = TRs_per_window  # size of the batch used at each step
        self.node_size = node_size  # num of ROI
        self.sampling_size = sampling_size
        self.sc = sc  # matrix node_size x node_size structure connectivity
        self.sc_fitted = torch.tensor(sc, dtype=torch.float32)  # placeholder
        self.use_fit_gains = use_fit_gains  # flag for fitting gains
        self.use_Laplacian = use_Laplacian
        self.use_Bifurcation = use_Bifurcation
        self.use_Gaussian_EI = use_Gaussian_EI
        self.use_dynamic_boundary = use_dynamic_boundary
        self.param = param

        self.output_size = node_size  # number of EEG channels
    
    def info(self):
        return {"state_names": ['E', 'I', 'x', 'f', 'v', 'q'], "output_names": ["bold"]}
    
    def createIC(self, ver):
        # initial state
        return torch.tensor(0.2 * np.random.uniform(0, 1, (self.node_size, self.state_size)) + np.array(
                [0, 0, 0, 1.0, 1.0, 1.0]), dtype=torch.float32)

    def setModelParameters(self):
        # set states E I f v mean and 1/sqrt(variance)
        return setModelParameters(self)

    def forward(self, external, hx, hE):
        return integration_forward(self, external, hx, hE)

def h_tf(a, b, d, z):
    """
    Neuronal input-output functions of excitatory pools and inhibitory pools.
    Take the variables a, x, and b and convert them to a linear equation (a*x - b) while adding a small
    amount of noise 0.00001 while dividing that term to an exponential of the linear equation multiplied by the
    d constant for the appropriate dimensions.
    """
    num = 0.00001 + torch.abs(a * z - b)
    den = 0.00001 * d + torch.abs(1.0000 - torch.exp(-d * (a * z - b)))
    return torch.divide(num, den)

def setModelParameters(model):
    param_reg = []
    param_hyper = []
    if model.use_Gaussian_EI:
        model.E_m = Parameter(torch.tensor(0.16, dtype=torch.float32))
        param_hyper.append(model.E_m)
        model.I_m = Parameter(torch.tensor(0.1, dtype=torch.float32))
        param_hyper.append(model.I_m)
        # model.f_m = Parameter(torch.tensor(1.0, dtype=torch.float32))
        model.v_m = Parameter(torch.tensor(1.0, dtype=torch.float32))
        param_hyper.append(model.v_m)
        # model.x_m = Parameter(torch.tensor(0.16, dtype=torch.float32))
        model.q_m = Parameter(torch.tensor(1.0, dtype=torch.float32))
        param_hyper.append(model.q_m)

        model.E_v_inv = Parameter(torch.tensor(2500, dtype=torch.float32))
        param_hyper.append(model.E_v_inv)
        model.I_v_inv = Parameter(torch.tensor(2500, dtype=torch.float32))
        param_hyper.append(model.I_v_inv)
        # model.f_v = Parameter(torch.tensor(100, dtype=torch.float32))
        model.v_v_inv = Parameter(torch.tensor(100, dtype=torch.float32))
        param_hyper.append(model.v_v_inv)
        # model.x_v = Parameter(torch.tensor(100, dtype=torch.float32))
        model.q_v_inv = Parameter(torch.tensor(100, dtype=torch.float32))
        param_hyper.append(model.v_v_inv)

    # hyper parameters (variables: need to calculate gradient) to fit density
    # of gEI and gIE (the shape from the bifurcation analysis on an isolated node)
    if model.use_Bifurcation:
        model.sup_ca = Parameter(torch.tensor(0.5, dtype=torch.float32))
        param_hyper.append(model.sup_ca)
        model.sup_cb = Parameter(torch.tensor(20, dtype=torch.float32))
        param_hyper.append(model.sup_cb)
        model.sup_cc = Parameter(torch.tensor(10, dtype=torch.float32))
        param_hyper.append(model.sup_cc)

    # set gains_con as Parameter if fit_gain is True
    if model.use_fit_gains:
        model.gains_con = Parameter(torch.tensor(np.zeros((model.node_size, model.node_size)) + 0.05,
                                                 dtype=torch.float32))  # connenction gain to modify empirical sc
        param_reg.append(model.gains_con)
    else:
        model.gains_con = torch.tensor(np.zeros((model.node_size, model.node_size)), dtype=torch.float32)

    var_names = [a for a in dir(model.param) if not a.startswith('__')]
    for var_name in var_names:
        var = getattr(model.param, var_name)
        if (type(var) == par): 
            if (var.fit_hyper == True):
                var.randSet() #TODO: This should be done before giving params to model class
                param_hyper.append(var.prior_mean)
                param_hyper.append(var.prior_var) #TODO: Currently this is _v_inv but should set everything to just variance unless there is a reason to keep the inverse?
            if (var.fit_par == True):
                param_reg.append(var.val) #TODO: This should got before fit_hyper, but need to change where randomness gets added in the code first
            setattr(model, var_name, var.val)

    model.params_fitted = {'modelparameter': param_reg,'hyperparameter': param_hyper}

def integration_forward(model, external, hx, hE):

    """
    Forward step in simulating the BOLD signal.
    Parameters
    ----------
    external: tensor with node_size x steps_per_TR x TRs_per_window x input_size
        noise for states

    hx: tensor with node_size x state_size
        states of WWD model
    Outputs
    -------
    next_state: dictionary with keys:
    'current_state''bold_window''E_window''I_window''x_window''f_window''v_window''q_window'
        record new states and BOLD
    """
    next_state = {}

    # hx is current state (6) 0: E 1:I (neural activities) 2:x 3:f 4:v 5:f (BOLD)

    x = hx[:, 2:3]
    f = hx[:, 3:4]
    v = hx[:, 4:5]
    q = hx[:, 5:6]

    dt = torch.tensor(model.step_size, dtype=torch.float32)

    # Generate the ReLU module for model parameters gEE gEI and gIE
    m = torch.nn.ReLU()

    # Update the Laplacian based on the updated connection gains gains_con.
    if model.sc.shape[0] > 1:

        # Update the Laplacian based on the updated connection gains gains_con.
        sc_mod = torch.exp(model.gains_con) * torch.tensor(model.sc, dtype=torch.float32)
        sc_mod_normalized = (0.5 * (sc_mod + torch.transpose(sc_mod, 0, 1))) / torch.linalg.norm(
            0.5 * (sc_mod + torch.transpose(sc_mod, 0, 1)))
        model.sc_fitted = sc_mod_normalized

        if model.use_Laplacian:
            lap_adj = -torch.diag(sc_mod_normalized.sum(1)) + sc_mod_normalized
        else:
            lap_adj = sc_mod_normalized

    else:
        lap_adj = torch.tensor(np.zeros((1, 1)), dtype=torch.float32)

    # placeholder for the updated current state
    current_state = torch.zeros_like(hx)

    # placeholders for output BOLD, history of E I x f v and q
    # placeholders for output BOLD, history of E I x f v and q
    bold_window = torch.zeros((model.node_size, model.TRs_per_window))
    # E_window = torch.zeros((model.node_size,model.TRs_per_window))
    # I_window = torch.zeros((model.node_size,model.TRs_per_window))

    x_window = torch.zeros((model.node_size, model.TRs_per_window))
    f_window = torch.zeros((model.node_size, model.TRs_per_window))
    v_window = torch.zeros((model.node_size, model.TRs_per_window))
    q_window = torch.zeros((model.node_size, model.TRs_per_window))

    E_hist = torch.zeros((model.node_size, model.TRs_per_window, model.steps_per_TR))
    I_hist = torch.zeros((model.node_size, model.TRs_per_window, model.steps_per_TR))
    E_mean = hx[:, 0:1]
    I_mean = hx[:, 1:2]
    # print(E_m.shape)
    # Use the forward model to get neural activity at ith element in the window.
    if model.use_dynamic_boundary:
        for TR_i in range(model.TRs_per_window):

            # print(E.shape)

            # Since tr is about second we need to use a small step size like 0.05 to integrate the model states.
            for step_i in range(model.steps_per_TR):
                E = torch.zeros((model.node_size, model.sampling_size))
                I = torch.zeros((model.node_size, model.sampling_size))
                for sample_i in range(model.sampling_size):
                    E[:, sample_i] = E_mean[:, 0] + 0.02 * torch.randn(model.node_size)
                    I[:, sample_i] = I_mean[:, 0] + 0.001 * torch.randn(model.node_size)

                # Calculate the input recurrent.
                IE = torch.tanh(m(model.W_E * model.I_0 + (0.001 + m(model.g_EE)) * E
                                  + model.g * torch.matmul(lap_adj, E) - (
                                          0.001 + m(model.g_IE)) * I))  # input currents for E
                II = torch.tanh(m(model.W_I * model.I_0 + (0.001 + m(model.g_EI)) * E - I))  # input currents for I

                # Calculate the firing rates.
                rE = h_tf(model.aE, model.bE, model.dE, IE)  # firing rate for E
                rI = h_tf(model.aI, model.bI, model.dI, II)  # firing rate for I
                # Update the states by step-size 0.05.
                E_next = E + dt * (-E * torch.reciprocal(model.tau_E) + model.gamma_E * (1. - E) * rE) \
                         + torch.sqrt(dt) * torch.randn(model.node_size, model.sampling_size) * (0.02 + m(
                    model.std_in))  ### equlibrim point at E=(tau_E*gamma_E*rE)/(1+tau_E*gamma_E*rE)
                I_next = I + dt * (-I * torch.reciprocal(model.tau_I) + model.gamma_I * rI) \
                         + torch.sqrt(dt) * torch.randn(model.node_size, model.sampling_size) * (
                                 0.02 + m(model.std_in))

                # Calculate the saturation for model states (for stability and gradient calculation).

                # E_next[E_next>=0.9] = torch.tanh(1.6358*E_next[E_next>=0.9])
                E = torch.tanh(0.0000 + m(1.0 * E_next))
                I = torch.tanh(0.0000 + m(1.0 * I_next))

                I_mean = I.mean(1)[:, np.newaxis]
                E_mean = E.mean(1)[:, np.newaxis]
                I_mean[I_mean < 0.00001] = 0.00001
                E_mean[E_mean < 0.00001] = 0.00001

                E_hist[:, TR_i, step_i] = E_mean[:, 0]
                I_hist[:, TR_i, step_i] = I_mean[:, 0]

        for TR_i in range(model.TRs_per_window):

            for step_i in range(model.steps_per_TR):
                x_next = x + 1 * dt * (1 * E_hist[:, TR_i, step_i][:, np.newaxis] - torch.reciprocal(
                    model.tau_s) * x - torch.reciprocal(model.tau_f) * (f - 1))
                f_next = f + 1 * dt * x
                v_next = v + 1 * dt * (f - torch.pow(v, torch.reciprocal(model.alpha))) * torch.reciprocal(
                    model.tau_0)
                q_next = q + 1 * dt * (
                        f * (1 - torch.pow(1 - model.rho, torch.reciprocal(f))) * torch.reciprocal(
                    model.rho) - q * torch.pow(v, torch.reciprocal(model.alpha)) * torch.reciprocal(v)) \
                         * torch.reciprocal(model.tau_0)

                x = torch.tanh(x_next)
                f = (1 + torch.tanh(f_next - 1))
                v = (1 + torch.tanh(v_next - 1))
                q = (1 + torch.tanh(q_next - 1))
                # Put x f v q from each tr to the placeholders for checking them visually.
            x_window[:, TR_i] = x[:, 0]
            f_window[:, TR_i] = f[:, 0]
            v_window[:, TR_i] = v[:, 0]
            q_window[:, TR_i] = q[:, 0]

            # Put the BOLD signal each tr to the placeholder being used in the cost calculation.

            bold_window[:, TR_i] = ((0.00 + m(model.std_out)) * torch.randn(model.node_size, 1) +
                                    100.0 * model.V * torch.reciprocal(model.E0) *
                                    (model.k1 * (1 - q) + model.k2 * (1 - q * torch.reciprocal(v)) + model.k3 * (
                                            1 - v)))[:, 0]
    else:

        for TR_i in range(model.TRs_per_window):

            # print(E.shape)

            # Since tr is about second we need to use a small step size like 0.05 to integrate the model states.
            for step_i in range(model.steps_per_TR):
                E = torch.zeros((model.node_size, model.sampling_size))
                I = torch.zeros((model.node_size, model.sampling_size))
                for sample_i in range(model.sampling_size):
                    E[:, sample_i] = E_mean[:, 0] + 0.001 * torch.randn(model.node_size)
                    I[:, sample_i] = I_mean[:, 0] + 0.001 * torch.randn(model.node_size)

                # Calculate the input recurrent.
                IE = 1 * torch.tanh(m(model.W_E * model.I_0 + (0.001 + m(model.g_EE)) * E \
                                      + model.g * torch.matmul(lap_adj, E) - (
                                              0.001 + m(model.g_IE)) * I))  # input currents for E
                II = 1 * torch.tanh(
                    m(model.W_I * model.I_0 + (0.001 + m(model.g_EI)) * E - I))  # input currents for I

                # Calculate the firing rates.
                rE = h_tf(model.aE, model.bE, model.dE, IE)  # firing rate for E
                rI = h_tf(model.aI, model.bI, model.dI, II)  # firing rate for I
                # Update the states by step-size 0.05.
                E_next = E + dt * (-E * torch.reciprocal(model.tau_E) + model.gamma_E * (1. - E) * rE) \
                         + torch.sqrt(dt) * torch.randn(model.node_size, model.sampling_size) * (0.02 + m(
                    model.std_in))  ### equlibrim point at E=(tau_E*gamma_E*rE)/(1+tau_E*gamma_E*rE)
                I_next = I + dt * (-I * torch.reciprocal(model.tau_I) + model.gamma_I * rI) \
                         + torch.sqrt(dt) * torch.randn(model.node_size, model.sampling_size) * (
                                 0.02 + m(model.std_in))

                # Calculate the saturation for model states (for stability and gradient calculation).
                E_next[E_next < 0.00001] = 0.00001
                I_next[I_next < 0.00001] = 0.00001
                # E_next[E_next>=0.9] = torch.tanh(1.6358*E_next[E_next>=0.9])
                E = E_next  # torch.tanh(0.00001+m(1.0*E_next))
                I = I_next  # torch.tanh(0.00001+m(1.0*I_next))

                I_mean = I.mean(1)[:, np.newaxis]
                E_mean = E.mean(1)[:, np.newaxis]
                E_hist[:, TR_i, step_i] = torch.tanh(E_mean)[:, 0]
                I_hist[:, TR_i, step_i] = torch.tanh(I_mean)[:, 0]

            # E_window[:,TR_i]=E_mean[:,0]
            # I_window[:,TR_i]=I_mean[:,0]

        for TR_i in range(model.TRs_per_window):

            for step_i in range(model.steps_per_TR):
                x_next = x + 1 * dt * (1 * E_hist[:, TR_i, step_i][:, np.newaxis] - torch.reciprocal(
                    model.tau_s) * x - torch.reciprocal(model.tau_f) * (f - 1))
                f_next = f + 1 * dt * x
                v_next = v + 1 * dt * (f - torch.pow(v, torch.reciprocal(model.alpha))) * torch.reciprocal(
                    model.tau_0)
                q_next = q + 1 * dt * (
                        f * (1 - torch.pow(1 - model.rho, torch.reciprocal(f))) * torch.reciprocal(
                    model.rho) - q * torch.pow(v, torch.reciprocal(model.alpha)) * torch.reciprocal(v)) \
                         * torch.reciprocal(model.tau_0)

                f_next[f_next < 0.001] = 0.001
                v_next[v_next < 0.001] = 0.001
                q_next[q_next < 0.001] = 0.001
                x = x_next  # torch.tanh(x_next)
                f = f_next  # (1 + torch.tanh(f_next - 1))
                v = v_next  # (1 + torch.tanh(v_next - 1))
                q = q_next  # (1 + torch.tanh(q_next - 1))
            # Put x f v q from each tr to the placeholders for checking them visually.
            x_window[:, TR_i] = x[:, 0]
            f_window[:, TR_i] = f[:, 0]
            v_window[:, TR_i] = v[:, 0]
            q_window[:, TR_i] = q[:, 0]
            # Put the BOLD signal each tr to the placeholder being used in the cost calculation.

            bold_window[:, TR_i] = ((0.00 + m(model.std_out)) * torch.randn(model.node_size, 1) +
                                    100.0 * model.V * torch.reciprocal(
                        model.E0) * (model.k1 * (1 - q) + model.k2 * (
                            1 - q * torch.reciprocal(v)) + model.k3 * (1 - v)))[:, 0]

    # Update the current state.
    # print(E_m.shape)
    current_state = torch.cat([E_mean, I_mean, x, f, v, q], dim=1)
    next_state['current_state'] = current_state
    next_state['bold_window'] = bold_window
    next_state['E_window'] = E_hist.reshape((model.node_size, -1))
    next_state['I_window'] = I_hist.reshape((model.node_size, -1))
    next_state['x_window'] = x_window
    next_state['f_window'] = f_window
    next_state['v_window'] = v_window
    next_state['q_window'] = q_window

    return next_state, hE