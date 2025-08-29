



@app.get("/status")
async def api_status(
    match: Optional[str] = Query(None),
    running: bool = Query(False),
):
    return free_status(match=match, running=running)


def free_logs(service_name: str, n_lines: int = 1000):
    """Get service logs - free function."""
    logger.info(f"logs called for service_name={service_name}, n_lines={n_lines}")
    return with_hostname({"logs": service_logs(service_name, n_lines)})


@app.get("/logs/{service_name}")
async def api_logs(
    service_name: str,
    n_lines: int = Query(1000, description="Number of log lines to return"),
):
    return free_logs(service_name=service_name, n_lines=n_lines)


def free_create(search_in: str, include: Optional[str] = None, exclude: Optional[str] = None):
    """Create services and dashboards - free function."""
    logger.info(
        f"create called with search_in={search_in}, include={include}, exclude={exclude}"
    )
    # Now that deploy.py uses services, let's use the original approach
    services = class_inst(class_type=Service, search_in=search_in)
    print(f"Found {len(services)} services")

    for sr in class_inst(class_type=ServiceRegistry, search_in=search_in):
        print(f"ServiceRegistry found with {len(sr.services)} services")
        services.extend(sr.services)

    dashboards = class_inst(class_type=Dashboard, search_in=search_in)
    print(f"Found {len(dashboards)} dashboards")

    print(f"Total services: {len(services)}")
    if include:
        services = [s for s in services if fnmatchcase(name=s.name, pat=include)]
        dashboards = [d for d in dashboards if fnmatchcase(name=d.title, pat=include)]

    if exclude:
        services = [s for s in services if not fnmatchcase(name=s.name, pat=exclude)]
        dashboards = [
            d for d in dashboards if not fnmatchcase(name=d.title, pat=exclude)
        ]

    for srv in services:
        srv.create(defer_reload=True)
    for dashboard in dashboards:
        dashboard.create()
    reload_unit_files()

    logger.info(
        f"create created {len(services)} services, {len(dashboards)} dashboards"
    )
    return with_hostname(
        {
            "services": [s.name for s in services],
            "dashboards": [d.title for d in dashboards],
        }
    )


@app.post("/create")
async def api_create(
    search_in: str = Body(..., embed=True),
    include: Optional[str] = Body(None, embed=True),
    exclude: Optional[str] = Body(None, embed=True),
):
    return free_create(search_in=search_in, include=include, exclude=exclude)


def free_start(match: str, timers: bool = False, services: bool = False):
    """Start services/timers - free function."""
    logger.info(
        f"start called with match={match}, timers={timers}, services={services}"
    )
    if (services and timers) or (not services and not timers):
        unit_type = None
    elif services:
        unit_type = "service"
    elif timers:
        unit_type = "timer"
    files = get_unit_files(match=match, unit_type=unit_type)
    _start_service(files)
    logger.info(f"start started {len(files)} units")
    return with_hostname({"started": files})


@app.post("/start")
async def api_start(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    return free_start(match=match, timers=timers, services=services)


def free_stop(match: str, timers: bool = False, services: bool = False):
    """Stop services/timers - free function."""
    logger.info(
        f"stop called with match={match}, timers={timers}, services={services}"
    )
    if (services and timers) or (not services and not timers):
        unit_type = None
    elif services:
        unit_type = "service"
    elif timers:
        unit_type = "timer"
    files = get_unit_files(match=match, unit_type=unit_type)
    _stop_service(files)
    logger.info(f"stop stopped {len(files)} units")
    return with_hostname({"stopped": files})


@app.post("/stop")
async def api_stop(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    return free_stop(match=match, timers=timers, services=services)


def free_restart(match: str):
    """Restart services - free function."""
    logger.info(f"restart called with match={match}")
    files = get_unit_files(match=match, unit_type="service")
    _restart_service(files)
    logger.info(f"restart restarted {len(files)} units")
    return with_hostname({"restarted": files})


@app.post("/restart")
async def api_restart(
    match: str = Body(..., embed=True),
):
    return free_restart(match=match)


def free_enable(match: str, timers: bool = False, services: bool = False):
    """Enable services/timers - free function."""
    logger.info(
        f"enable called with match={match}, timers={timers}, services={services}"
    )
    if (services and timers) or (not services and not timers):
        unit_type = None
    elif services:
        unit_type = "service"
    elif timers:
        unit_type = "timer"
    files = get_unit_files(match=match, unit_type=unit_type)
    _enable_service(files)
    logger.info(f"enable enabled {len(files)} units")
    return with_hostname({"enabled": files})


@app.post("/enable")
async def api_enable(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    return free_enable(match=match, timers=timers, services=services)


def free_disable(match: str, timers: bool = False, services: bool = False):
    """Disable services/timers - free function."""
    logger.info(
        f"disable called with match={match}, timers={timers}, services={services}"
    )
    if (services and timers) or (not services and not timers):
        unit_type = None
    elif services:
        unit_type = "service"
    elif timers:
        unit_type = "timer"
    files = get_unit_files(match=match, unit_type=unit_type)
    _disable_service(files)
    logger.info(f"disable disabled {len(files)} units")
    return with_hostname({"disabled": files})


@app.post("/disable")
async def api_disable(
    match: str = Body(..., embed=True),
    timers: bool = Body(False, embed=True),
    services: bool = Body(False, embed=True),
):
    return free_disable(match=match, timers=timers, services=services)

def free_remove(match: str):
    """Remove services - free function."""
    logger.info(f"remove called with match={match}")
    service_files = get_unit_files(match=match, unit_type="service")
    timer_files = get_unit_files(match=match, unit_type="timer")
    _remove_service(
        service_files=service_files,
        timer_files=timer_files,
    )
    removed_names = [Path(f).name for f in service_files + timer_files]
    logger.info(f"remove removed {len(removed_names)} units")
    return with_hostname({"removed": removed_names})


@app.post("/remove")
async def api_remove(match: str = Body(..., embed=True)):
    return free_remove(match=match)


def free_show(match: str):
    """Show service files - free function."""
    logger.info(f"show called with match={match}")
    files = get_unit_files(match=match)
    logger.debug(f"show returned files for {match}")
    return with_hostname({"files": load_service_files(files)})


@app.get("/show/{match}")
async def api_show(
    match: str,
):
    return free_show(match=match)
