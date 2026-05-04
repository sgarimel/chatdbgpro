"""Capture rich debugger state at page fault or panic for enriched prompt."""
import lldb
import time
import json
import os


def capture_state(debugger, command, result, internal_dict):
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()

    bp_ut = target.BreakpointCreateByName('usertrap')
    bp_panic = target.BreakpointCreateByName('panic')
    print(f'[capture] breakpoints set, iterating...')

    found = False
    for i in range(500):
        process.Continue()
        for _ in range(10):
            if process.GetState() == lldb.eStateStopped:
                break
            time.sleep(0.05)
        if process.GetState() != lldb.eStateStopped:
            continue

        thread = process.GetSelectedThread()
        frame = thread.GetSelectedFrame()
        fn = frame.GetFunctionName() or ''

        if 'panic' in fn:
            print(f'[capture] HIT PANIC at iteration {i}')
            found = True
            break

        sc_reg = frame.FindRegister('scause')
        sc = sc_reg.GetValueAsUnsigned(0) if sc_reg.IsValid() else -1

        if sc in (12, 13, 15):
            labels = {12: "instruction page fault", 13: "load page fault", 15: "store page fault"}
            sepc = frame.FindRegister('sepc')
            stval = frame.FindRegister('stval')
            print(f'[capture] PAGE FAULT at iteration {i}')
            print(f'  scause = {sc} ({labels.get(sc)})')
            print(f'  sepc   = {sepc.GetValue()}')
            print(f'  stval  = {stval.GetValue()}')

            # Dump backtrace
            print('\nBacktrace:')
            for f in thread:
                print(f'  {f}')

            # Print source at usertrap
            print('\nSource at usertrap:')
            debugger.HandleCommand('source list -n usertrap -c 50')

            found = True
            break

    if not found:
        print(f'[capture] WARNING: no fault/panic in 500 iterations')

    # Clean up
    target.BreakpointDelete(bp_ut.GetID())
    target.BreakpointDelete(bp_panic.GetID())


def __lldb_init_module(debugger, internal_dict):
    debugger.HandleCommand(
        'command script add -f capture_rich_state.capture_state capture_state'
    )
    print('[capture_rich_state] Loaded. Use: capture_state')
