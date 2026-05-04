"""LLDB Python script: skip syscall traps, stop at page fault or panic."""
import lldb
import time


def catch_page_fault(debugger, command, result, internal_dict):
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    # Set breakpoints on both usertrap (for page faults) AND panic
    bp_usertrap = target.BreakpointCreateByName('usertrap')
    bp_panic = target.BreakpointCreateByName('panic')
    print(f'[catch_fault] breakpoints: usertrap={bp_usertrap.GetID()}, panic={bp_panic.GetID()}')

    for i in range(200):
        process.Continue()
        # Wait for stop
        for _ in range(30):
            if process.GetState() == lldb.eStateStopped:
                break
            time.sleep(0.1)

        if process.GetState() != lldb.eStateStopped:
            print(f'[catch_fault] process not stopped after continue #{i}')
            continue

        thread = process.GetSelectedThread()
        frame = thread.GetSelectedFrame()
        fn = frame.GetFunctionName() or ""

        # Check if we hit panic — this is our target for bugs that panic
        if 'panic' in fn:
            print(f'[catch_fault] *** HIT PANIC at iteration {i} ***')
            print('\nBacktrace:')
            for f in thread:
                print(f'  {f}')
            # Print panic message (first arg)
            msg = frame.EvaluateExpression('(char*)s')
            print(f'\npanic message: {msg.GetSummary()}')
            # Clean up breakpoints
            target.BreakpointDelete(bp_usertrap.GetID())
            target.BreakpointDelete(bp_panic.GetID())
            break

        # Check if we're in usertrap — look at scause for page faults
        if 'usertrap' in fn:
            scause_reg = frame.FindRegister('scause')
            sc = scause_reg.GetValueAsUnsigned(0) if scause_reg.IsValid() else -1

            if sc in (12, 13, 15):
                labels = {12: "instr_pf", 13: "load_pf", 15: "store_pf"}
                print(f'[catch_fault] *** PAGE FAULT scause={sc} ({labels.get(sc,"?")}) at iteration {i} ***')
                print('\nBacktrace:')
                for f in thread:
                    print(f'  {f}')
                sepc = frame.FindRegister('sepc')
                stval = frame.FindRegister('stval')
                print(f'\nscause = {sc} ({labels.get(sc,"?")})')
                print(f'sepc   = {sepc.GetValue()}')
                print(f'stval  = {stval.GetValue()}')
                pid_expr = frame.EvaluateExpression('myproc()->pid')
                print(f'pid    = {pid_expr.GetValue()}')
                target.BreakpointDelete(bp_usertrap.GetID())
                target.BreakpointDelete(bp_panic.GetID())
                break
            # else: scause=8 (syscall) or other — skip
    else:
        print('[catch_fault] WARNING: did not hit fault or panic in 200 iterations')
        # Clean up anyway
        target.BreakpointDelete(bp_usertrap.GetID())
        target.BreakpointDelete(bp_panic.GetID())


def __lldb_init_module(debugger, internal_dict):
    debugger.HandleCommand(
        'command script add -f catch_fault.catch_page_fault catch_fault'
    )
    print('[catch_fault] Loaded. Use: catch_fault')
