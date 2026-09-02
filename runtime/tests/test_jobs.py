async def test_enqueue_run_retry_and_dead_letter(sf, fixed_clock):
    from spatalk import jobs
    calls = []

    @jobs.register_handler("test.ok")
    async def ok(payload, ctx):
        calls.append(payload["n"])

    @jobs.register_handler("test.fail")
    async def fail(payload, ctx):
        raise RuntimeError("boom")

    ctx = jobs.JobContext(sf=sf, clock=fixed_clock, registry=None, ledger=None, delivery=None, settings=None)
    await jobs.enqueue(sf, "test.ok", {"n": 1})
    jid = await jobs.enqueue(sf, "test.fail", {})
    assert await jobs.run_once(sf, ctx) == 2
    assert calls == [1]
    job = await jobs.get_job(sf, jid)
    assert job.state == "queued" and job.attempts == 1 and "boom" in job.last_error
    assert job.run_at > fixed_clock.now()
    for _ in range(4):
        fixed_clock.advance(hours=1)
        await jobs.run_once(sf, ctx)
    assert (await jobs.get_job(sf, jid)).state == "dead"
