import os
import sys
from multiprocessing import freeze_support

from textual import on, events
from textual.app import App, ComposeResult
from textual.widgets import (
    Footer,
    Header,
    Label,
    ProgressBar,
    Rule,
    TabbedContent,
    Tree,
    Placeholder,
    DataTable,
    TextArea,
)
from textual.containers import Container, Horizontal, Center

from dicombrowser.dicom import DicomSeries, load_dicom_dir, load_dicom_zip, SERIES_LIST_COLUMNS

CSS = """
DataTable {
    height: 10;
}

ProgressBar {
    width: 95%;
}
/* Target the inner rendered bar component inside the ProgressBar */
ProgressBar > Bar {
    width: 1fr;
}

Rule {
    margin: 0 2; /* top/bottom: 0 cell, left/right: 2 cells */
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

        # Calculate where the click happened relative to the widget width
        # event.x is the column index where the mouse clicked inside the widget
        click_fraction = event.x / self.size.width
        new_progress = int(0.5 + click_fraction * self.total)
        clamped_progress = max(0.0, min(new_progress, self.total))
        self.update(progress=clamped_progress)
        self.app.post_message(self.Seeked(clamped_progress))


class DicomBrowserCLI(App):
    """A Textual app to manage stopwatches."""

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
        self.sel_image_text = Label("Image #??")
        self.text = TextArea(id="text")
        self.attr_tree = Tree(label="Attributes", id="attributes")
        self.series = {}

    def compose(self) -> ComposeResult:
        yield Header()

        self.series_table.add_columns(*self.series_columns)
        yield self.series_table

        with Horizontal(id="sel_image_h"):
            yield self.sel_image_text
            with Center():
                yield self.sel_image

        with TabbedContent("Text", "Attributes", "Preview"):
            yield self.text
            yield self.attr_tree
            yield Placeholder(label="preview", id="preview")

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

    # def on_data_table_row_selected(self,event: DataTable.RowSelected):
    #     row_key = event.row_key
    #     row_data = self.series_table.get_row(row_key)
    #     self.text.text=f"{(row_key,row_data)}"
    #     self.title=str(row_key)

    # @on(DataTable.RowSelected)
    # def handle_row_selection(self, event: DataTable.RowSelected) -> None:
    #     row_key = event.row_key
    #     row_data = self.series_table.get_row(row_key)
    #     self.text.text=f"{(row_key,row_data)}"
    #     self.title=str(row_key)

    @on(DataTable.RowHighlighted)
    def handle_cursor_movement(self, event: DataTable.RowHighlighted) -> None:
        # Avoid crashing if the highlight event triggers on an empty table
        if event.row_key is None:
            return

        uid, *_ = self.series_table.get_row(event.row_key)
        if uid in self.series:
            series: DicomSeries = self.series[uid]
            self.text.text = str(series.get_attr_object(0))
            self.sel_image.total = series.num_files
            self.sel_image.progress = series.num_files // 2


def mainargv_cli():
    """setuptools compatible entry point."""
    freeze_support()
    DicomBrowserCLI(sys.argv).run()


if __name__ == "__main__":
    mainargv_cli()
