import sys
import argparse
import os

sys.path.append("./openvisuspy/src/")
if __name__.startswith("bokeh"):
    from openvisuspy import SetupLogger, IsPanelServe, GetBackend, Slices

    logger = SetupLogger()
    logger.info(f"GetBackend()={GetBackend()}")

    if os.environ.get("DATA") == "remote":
        remote_dir = "https://maritime.sealstorage.io/api/v0/s3/utah/nsdf/somospie/terrain_tennessee/Tennessee_terrain_parameters.idx?access_key=any&secret_key=any&endpoint_url=https://maritime.sealstorage.io/api/v0/s3&cached=arco"
    else:
        remote_dir = "idx_data/Tennessee_terrain_parameters.idx"

    is_panel = IsPanelServe()
    if is_panel:
        import panel as pn

        doc = None
    else:
        import bokeh

        doc = bokeh.io.curdoc()
        doc.theme = "light_minimal"

    if False:
        view = Slice(
            doc=doc,
            is_panel=is_panel,
        )
        view.setShowOptions(
            [
                "direction",
                "offset",
                "palette",
                "field",
                "resolution",
                "colormapper_type",
                "palette_range_mode",
                "palette_range_vmin",
                "palette_range_vmax",
            ]
        )
    else:
        view = Slices(doc=doc, is_panel=is_panel)
        view.setShowOptions(
            [
                ["palette", "resolution", "field", "colormapper_type"],
                [
                    "direction",
                    "offset",
                    "field",
                    "colormapper_type",
                    "palette_range_mode",
                    "palette_range_vmin",
                    "palette_range_vmax",
                ],
            ]
        )

    view.setDataset(remote_dir)

    if is_panel:
        main_layout = view.getMainLayout()
        use_template = True
        if use_template:
            template = pn.template.MaterialTemplate(title="SOMOSPIE Integration")
            template.main.append(main_layout)
            template.servable()
        else:
            main_layout.servable()
    else:
        # view.setMetadataPaletteRange([0,255])

        main_layout = view.getMainLayout()
        view.setPaletteRangeMode("user")
        view.setPaletteRange([0, 360])
        view.setResolution(21)
        doc.add_root(main_layout)
