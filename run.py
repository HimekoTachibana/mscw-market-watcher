import sys

if __name__ == "__main__":
    from mesowatcher import portable
    portable.setup()  # the packaged program uses the browser and libraries it ships with
    if "--selftest" in sys.argv[1:]:  # headless check used by CI; see mesowatcher/selftest.py
        from mesowatcher.selftest import main as selftest
        sys.exit(selftest(sys.argv[1:]))
    from mesowatcher.app import main
    main()
