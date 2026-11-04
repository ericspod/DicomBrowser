import os
import sys
import re
from multiprocessing import freeze_support

from textual import on, events, work
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, Label, ProgressBar, Static, DataTable
from textual.containers import Horizontal, Center, Vertical
from dicombrowser.dicom import DicomSeries, load_dicom_dir, load_dicom_zip, SERIES_LIST_COLUMNS, ATTR_TREE_COLUMNS

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


def iter_attrs(dcm, regex=None, max_value_len=256, depth=0):
    try:
        regex = re.compile(str(regex), re.DOTALL) if regex else None
    except:
        regex = None  # no regex or bad pattern

    prefix = "  " * depth
    for elem in dcm:
        if elem.name == "Pixel Data":
            continue

        if regex is not None and re.search(regex, f"{elem.name} {elem.tag} {elem.value}") is None:
            continue

        tag = f"{elem.tag.group:04x},{elem.tag.elem:04x}"
        if elem.VR == "SQ":
            yield prefix + elem.name, tag, "----"
            for subvalue in elem:
                yield from iter_attrs(subvalue, regex, max_value_len, depth + 1)
                yield prefix + "----", "----", "----"
        else:
            value = str(elem.value)
            if len(value) > max_value_len:
                value = value[:max_value_len] + "..."

            try:
                value = value.decode("ascii")
                if "\n" in value or "\r" in value:  # multiline text data should be shown as repr
                    value = repr(value)
            except:
                pass

            yield prefix + elem.name, tag, value


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
        self.attr_columns = list(ATTR_TREE_COLUMNS)
        self.series_table = DataTable(id="series", cursor_type="row", zebra_stripes=True)
        self.sel_image = ClickableProgressBar(show_percentage=False, show_eta=False, show_bar=True, total=1)
        self.sel_image_text = Label("Image #???")
        self.sel_image_idx = 0
        self.attr_table = DataTable(id="attributes", zebra_stripes=True)
        self.attr_regex = Input(id="regex", compact=True)
        self.series: dict[str, DicomSeries] = {}
        self.selected_series: DicomSeries = None

    def compose(self) -> ComposeResult:
        self.series_table.add_columns(*self.series_columns)
        self.attr_table.add_columns(*self.attr_columns)

        yield Header()
        yield self.series_table

        # image scroll label and bar
        with Horizontal(id="sel_image_h"):
            yield self.sel_image_text
            with Center():
                yield self.sel_image

        with Vertical():  # needed to ensure table's size and position are correct
            # filter regex text box
            with Horizontal(id="regex_h"):
                yield Label("Filter: ")
                yield self.attr_regex

            yield self.attr_table
            yield Static()

        yield Footer()

    def on_mount(self):
        for a in self.argv:
            self._load(a)

    @work(thread=True)
    def _load(self, src: str):
        def _stat(_, count, total):
            title = self.TITLE if total == 0 else f"Loading {src!r} ({count}/{total})"
            self.call_from_thread(setattr, self.app, "title", title)

        loader = load_dicom_dir if os.path.isdir(src) else load_dicom_zip
        self.call_from_thread(self._add_series, src, loader(src, _stat))

    def _add_series(self, src: str, series: list[DicomSeries]):
        self.series_table.add_row(f"---- {src} ----")
        self.series_table.add_rows(s.get_attr_values(self.series_columns) for s in series)
        self.series.update({str(s.series_id): s for s in series})

    def _select_series(self, uid):
        if uid in self.series:
            self.selected_series = self.series[uid]
            self.sel_image.total = self.selected_series.num_files - 1
            self._select_image(self.sel_image_idx)

    def _select_image(self, idx):
        if self.selected_series is None:
            return

        self.sel_image_idx = max(0, min(idx, self.selected_series.num_files - 1))
        self.sel_image.progress = self.sel_image_idx
        self.sel_image_text.content = f"Image #{self.sel_image_idx+1}"

        dcm = self.selected_series.get_attr_object(self.sel_image_idx)
        saved_coord = self.attr_table.cursor_coordinate
        self.attr_table.clear()
        self.attr_table.add_rows(iter_attrs(dcm, self.attr_regex.value))

        target_row = min(saved_coord.row, max(0, len(self.attr_table.rows) - 1))
        target_col = min(saved_coord.column, max(0, len(self.attr_table.columns) - 1))
        self.attr_table.move_cursor(row=target_row, column=target_col, scroll=False)

    def action_toggle_dark(self) -> None:
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def action_prev_image(self):
        self._select_image(self.sel_image_idx - 1)

    def action_next_image(self):
        self._select_image(self.sel_image_idx + 1)

    def on_clickable_progress_bar_seeked(self, message: ClickableProgressBar.Seeked):
        self._select_image(message.value)
        self.attr_table.focus()

    @on(DataTable.RowHighlighted)
    def handle_cursor_movement(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:  # row_key is None on an empty table
            uid, *_ = self.series_table.get_row(event.row_key)
            self._select_series(uid)

    def on_input_changed(self, message: Input.Changed):
        self._select_image(self.sel_image_idx)


def mainargv_cli():
    """setuptools compatible entry point."""
    freeze_support()
    DicomBrowserCLI(sys.argv[1:]).run()


if __name__ == "__main__":
    mainargv_cli()
