from mcp.server.fastmcp.resources import TextResource

_common = """
You don't need to fill in the function body, treat it as a function you can import 
from another library: eftqc_bench. So import it and focus on generating the 
input of this function.

Write code as concise as possible. Don't create wrapper for these functions or use
complicated print statements. Keep functions simple and avoid nesting over 2 layers.
"""

_trotter_qpe_eval_func_api = '''
def trotter_qpe_eval(
    qubit_hamiltonian: QubitHamiltonian,
    eps: float,
    w: float,
    device_funcs: Sequence[DeviceGenFunction],
    allow_diff_dt: bool = True,
    p: int = 1,
    alpha: float = np.pi / 2,
) -> pd.DataFrame:
    """Evaluate the performance of Trotter QPE.

    Args:
        qubit_hamiltonian: A QURI Algo :class:`QubitHamiltonian`.
        eps: The target accuracy.
        w: The Trotter error coefficient. Here we assume the Trotter error eps_{trott}
            is always given by :math:`eps_{trott} = w (dt)^2`.
        allow_diff_dt: If True, the value of dt used to generate the controlled-U^{2^k}
            can be different for different values of k. This will give better fidelity
            and run time. If False, all controlled-U^{2^k} uses the same value of dt.
        p: The Trotter order. Only supports p = 1 and p = 2.
        alpha: The number of repitition of U to reach `eps` accuracy is given by 
            :math:`\frac{alpha}{\epsilon}`. An optimistic value of \alpha is \pi / 2.
    """
    ...
'''


_qpe_eval = TextResource(
    uri="bench://qpe",
    name="trotter_qpe_eval",
    title="Trotter QPE Resource estimation",
    description=f"""
    Generate the input for the function "trotter_qpe_eval"
    """,
    text=f"""
    You are responsible for using QURI SDK to generate the input of the 
    trotter_qpe_eval_main function defined as {_trotter_qpe_eval_func_api}.

    Import the function with
    ```
    from eftqc_bench.tools.qpe import trotter_qpe_eval
    ```

    {_common}
    """,
)


_device_gen_func_api = '''
def device_gen_func_factory(
    logical_qubit_count: int,
    qec_cycle_us: float,
    logical_error_rate: float,
    t_gate_cycle: int | float,
    device_name: str
) -> DeviceGenFunction:
    """Generates the device property generation function.
    A :class:`DeviceGenFunction` is a function that generates the device
    property 

    Args:
        logical_qubit_count: Number of logical qubits.
        qec_cycle_us: QEC cycle time in the unit of microsecond
        logical_error_rate: Logical error rate per cycle.
        t_gate_cycle: Number of cycles of non-Clifford gates.
        device_name: Name of the device
    """
    ...
'''



_make_device_func_factory = TextResource(
    uri="bench://device",
    name="device_gen_func_eval",
    title="Device generation function factory from device specification",
    description=f"""
    Generate the input for the function "device_gen_func_factory"
    """,
    text=f"""
    You are responsible for understanding device specifications and 
    turn them into the input of {_device_gen_func_api}. This is an API
    for providing users to generate device properties easily by specifying
    the device specifications. 

    Import the function with 
    ```
    from eftqc_bench.tools.device_gen_func import device_gen_func_factory
    ```

    {_common}
    """,
)


_hamiltonian_gen_api = '''
def get_mole_qubit_hamiltonian(
    atom: Atoms, 
    basis: str = "sto-3g", 
    spin: float = 0.0, 
    charge: int = 0,
    n_active_orb: int | None = None,
    n_active_ele: int | None = None,
) -> QubitHamiltonian:
    """Generates molecular Hamiltonian.

    Args:
        atom: A string representing the coordinates of the atoms in a molecule.
        basis: The basis set for generating the Hamiltonian. Default to sto-3g.
        spin: The spin of the molecule. Follows the the standard convention of 
            sz=0.5 for spin-1/2. Default to 0.0.
        charge: Total charge of the molecule.
        n_active_orb: Number of active orbitals.
        n_active_ele: Number of active electrons.
    """
'''


_mole_hamiltonian_gen = TextResource(
    uri="bench://mole_hamiltonian",
    name="molecular_hamiltonian_generation",
    title="qubit molecular Hamiltonian generation.",
    description=f"""Generates the qubit molecular Hamiltonian.""",
    text=f"""
    You are responsible for generating molecular hamiltonian.
    Turn from user input into the input of {_hamiltonian_gen_api}. 
    If the user provides no active space information, n_active_orb,
    n_active_ele are both None. If user only provide n_active_orb, set
    n_active_ele to be the same value.

    Import the function with 
    ```
    from eftqc_bench.tools.mole_gen import get_mole_qubit_hamiltonian
    ```

    {_common}
    """,
)


_mole_data_gen_api = '''
def get_mole_data(
    atom: Atoms,
    basis: str = "sto-3g",
    spin: float = 0.0,
    charge: int = 0,
    n_active_orb: int | None = None,
    n_active_ele: int | None = None,
) -> MolecularData:
    """Generates molecular data.

    Args:
        atom: A string representing the coordinates of the atoms in a molecule.
        basis: The basis set for generating the Hamiltonian. Default to sto-3g.
        spin: The spin of the molecule. Follows the the standard convention of
            sz=0.5 for spin-1/2. Default to 0.0.
        charge: Total charge of the molecule.
        n_active_orb: Number of active orbitals.
        n_active_ele: Number of active electrons.
    """
'''


_mole_data_gen = TextResource(
    uri="bench://mole_data",
    name="molecular_data_generation",
    title="Molecular data generation",
    description=f"""Generate the MolecularData""",
    text=f"""
    You are responsible for generating molecular data. The molecular data is 
    a dataclass that holds the atoms, basis, spin, charge and active space size.
    This is used as a input for evaluating the DFQ QPE.
    Turn from user input into the input of {_mole_data_gen_api}. 
    
    If the user provides no active space information, n_active_orb,
    n_active_ele are both None. If user only provide n_active_orb, set
    n_active_ele to be the same value.

    Import the function with 
    ```
    from eftqc_bench.tools.mole_gen import get_mole_data
    ```

    {_common}
    """,
)



_trotter_eval = '''
def trotter_eval(
    qubit_hamiltonian: QubitHamiltonian,
    rs: Sequence[int] = (3, 5, 7, 9),
    p: int = 2
) -> float:
    """Estimates the trotter error coefficient w.

    Args:
        qubit_hamiltonian: The qubit Hamiltonian.
        rs: Number of Trotter steps for computing the Trotter error.
        p: The Trotter order. Only accept p = 1 or 2.
    """
'''

_trotter_eval_main = TextResource(
    uri="bench://trotter_eval",
    name="trotter_error_coefficient_eval",
    title="trotter_error_coefficient_eval",
    description=f"""
    Evaluate the Trotter error coefficient w.
    """,
    text=f"""
    You are responsible for evaluating the Trotter error coefficient.
    Turn from user input into the input of {_trotter_eval}. Be careful
    when you use this function.

    If you know the number of spatial orbital is larger than 6,
    make qubit Hamiltonians of smaller size, evaluate w for each of them
    and do a polynomial fit to get the w of the target n_orb.

    Import the function by
    ```
    from eftqc_bench.tools.trotter_eval import trotter_eval
    ```

    {_common}
    """,
)


_dfq_eval_api = '''
def dfq_eval(
    mole_data: MolecularData, 
    eps: float,
    eps_in: float,
    device_funcs: Sequence[DeviceGenFunction],
    qrom_k: int | None = None,
    beta_override: int | None = None,
) -> pd.DataFrame:
    """Evaluates the DF qubitization QPE (DFQ QPE)

    Args:
        mole_data: A :class:`MolecularData`.
        eps: The target accuracy one wants to reach.
        eps_in: Threshold for truncating the Hamiltonian in the incoherent scheme
            defined in arXiv:2007.14460. It is usually set to be the same as 
            (or slightly smaller than) eps.
        device_funcs: :class:`DeviceGenFunction` to evaluate DFQ QPE with.
        qrom_k: The parameter for optimizing the QROM in the circuit. When k=None, 
            it automatically chooses the optimal valus. However, we recommend to
            set it to 2 for fast evaluation. This will not give the optimal Toffoli
            count but can save a lot of ancilla qubits.
        beta_override: The value that determines how many bits are used to store the 
            rotation angle value. If None, it automatically selects the standard value.
    """
'''

_dfq_eval_main = TextResource(
    uri="bench://dfq_qpe_eval",
    name="dfq_qpe_evaluation",
    title="dfq_qpe_evaluation",
    description=f"""
    Evaluate the performance of DFQ QPE.
    """,
    text=f"""
    You are responsible for evaluating the DF qubitization QPE algorithm.
    Turn from user input into the input of {_dfq_eval_api}. 

    import the function with
    ```
    import code:
    from eftqc_bench.tools.dfq_eval import dfq_eval
    ```

    {_common}
    """,
)

all_bench_resources = (
    _qpe_eval, 
    _make_device_func_factory, 
    _mole_hamiltonian_gen, 
    _trotter_eval_main, 
    _mole_data_gen,
    _dfq_eval_main
)
