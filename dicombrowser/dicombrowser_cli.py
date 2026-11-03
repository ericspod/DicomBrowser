import os
import sys
from multiprocessing import freeze_support

from textual import on, events
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, Label, ProgressBar, Static, DataTable
from textual.containers import Horizontal, Center, Vertical
from dicombrowser.dicom import DicomSeries, load_dicom_dir, load_dicom_zip, SERIES_LIST_COLUMNS, ATTR_TREE_COLUMNS
from dicombrowser.models import get_attrs_seq

CSS = """
DataTable#series {
    height: 10;
}

ProgressBar {
    width: 95%;
}

Static { 
    height: 100%;
}

/* Target the inner rendered bar component inside the ProgressBar */
ProgressBar > Bar {
    width: 1fr;
}

Horizontal#sel_image_h {
    border: solid grey;
    height:3;
}
"""


class ClickableProgressBar(ProgressBar):

    class Seeked(events.Event):
        def __init__(self, value: float) -> None:
            super().__init__()
            self.value = value

    def on_click(self, event: events.Click) -> None:
        if self.total is None or self.total == 0 or self.size.width == 0:
            return

        click_fraction = event.x / self.size.width
        new_progress = int(0.5 + click_fraction * self.total)
        clamped_progress = max(0, min(new_progress, self.total))
        self.update(progress=clamped_progress)
        self.app.post_message(self.Seeked(clamped_progress))


class DicomBrowserCLI(App):
    BINDINGS = [
        ("a", "prev_image", "Previous Image"),
        ("d", "next_image", "Next Image"),
        ("m", "toggle_dark", "Toggle Dark Mode"),
        ("q", "quit", "Quit"),
    ]
    TITLE = "DicomBrowser"
    CSS = CSS

    def __init__(self, argv):
        super().__init__()
        self.argv = argv
        self.series_columns = list(SERIES_LIST_COLUMNS)  # keywords for columns
        self.series_table = DataTable(id="series", cursor_type="row", zebra_stripes=True)
        self.sel_image = ClickableProgressBar(show_percentage=False, show_eta=False, show_bar=True, total=1)
        self.sel_image_text = Label("Image #???")
        self.sel_image_idx = 0
        self.attr_table = DataTable(id="attributes", zebra_stripes=True)
        self.attr_regex = Input(id="regex", compact=True)
        self.series: dict[str, DicomSeries] = {}
        self.selected_series: DicomSeries = None

    def compose(self) -> ComposeResult:
        yield Header()

        self.series_table.add_columns(*self.series_columns)
        self.attr_table.add_columns(*ATTR_TREE_COLUMNS)

        yield self.series_table

        with Horizontal(id="sel_image_h"):
            yield self.sel_image_text
            with Center():
                yield self.sel_image

        with Vertical():
            with Horizontal(id="regex_h"):
                yield Label("Filter: ")
                yield self.attr_regex
            yield self.attr_table
            yield Static()

        yield Footer()

    def action_toggle_dark(self) -> None:
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def on_mount(self):
        for a in self.argv[1:]:
            self.series_table.add_row(a)
            loader = load_dicom_dir if os.path.isdir(a) else load_dicom_zip
            series: list[DicomSeries] = list(loader(a))
            rows = [s.get_attr_values(self.series_columns) for s in series]
            self.series_table.add_rows(rows)
            self.series.update({str(s.series_id): s for s in series})

    def _select_series(self, uid):
        if uid in self.series:
            self.selected_series = self.series[uid]
            self.sel_image.total = self.selected_series.num_files - 1
            self._set_image_idx(self.sel_image_idx)

    def _set_image_idx(self, idx):
        if self.selected_series is None:
            return

        self.sel_image_idx = max(0, min(idx, self.selected_series.num_files - 1))
        self.sel_image.progress = self.sel_image_idx
        self.sel_image_text.content = f"Image #{self.sel_image_idx+1}"

        dcm = self.selected_series.get_attr_object(self.sel_image_idx)
        self.attr_table.clear()
        for name, tag, value in get_attrs_seq(dcm, self.attr_regex.value):
            self.attr_table.add_row(name, tag, value if isinstance(value, str) else "[...]")

    def action_prev_image(self):
        self._set_image_idx(self.sel_image_idx - 1)

    def action_next_image(self):
        self._set_image_idx(self.sel_image_idx + 1)

    def on_clickable_progress_bar_seeked(self, message: ClickableProgressBar.Seeked):
        self._set_image_idx(message.value)

    @on(DataTable.RowHighlighted)
    def handle_cursor_movement(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:  # row_key is None on an empty table
            uid, *_ = self.series_table.get_row(event.row_key)
            self._select_series(uid)

    def on_input_changed(self, message: Input.Changed):
        self._set_image_idx(self.sel_image_idx)


def mainargv_cli():
    """setuptools compatible entry point."""
    freeze_support()
    DicomBrowserCLI(sys.argv).run()


if __name__ == "__main__":
    mainargv_cli()
