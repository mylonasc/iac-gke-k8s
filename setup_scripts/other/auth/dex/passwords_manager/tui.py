from __future__ import annotations

from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static

from .controller import PasswordsController, PasswordsError
from .models import StaticPasswordUser


@dataclass(slots=True)
class AddUserResult:
    email: str
    username: str
    user_id: str
    password: str


@dataclass(slots=True)
class EditUserResult:
    email: str
    username: str
    user_id: str


class AddUserScreen(ModalScreen[AddUserResult | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal"):
            yield Label("Create User")
            yield Input(placeholder="email", id="email")
            yield Input(placeholder="username", id="username")
            yield Input(placeholder="userID", id="user_id")
            yield Input(placeholder="password", password=True, id="password")
            yield Input(
                placeholder="confirm password", password=True, id="password_confirm"
            )
            yield Static("", id="error")
            with Horizontal():
                yield Button("Create", id="submit", variant="success")
                yield Button("Cancel", id="cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return

        email = self.query_one("#email", Input).value.strip()
        username = self.query_one("#username", Input).value.strip()
        user_id = self.query_one("#user_id", Input).value.strip()
        password = self.query_one("#password", Input).value
        password_confirm = self.query_one("#password_confirm", Input).value

        if not email or not username or not user_id:
            self.query_one("#error", Static).update(
                "Email, username, and userID are required."
            )
            return
        if not password:
            self.query_one("#error", Static).update("Password is required.")
            return
        if password != password_confirm:
            self.query_one("#error", Static).update("Passwords do not match.")
            return

        self.dismiss(
            AddUserResult(
                email=email, username=username, user_id=user_id, password=password
            )
        )


class EditUserScreen(ModalScreen[EditUserResult | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, user: StaticPasswordUser) -> None:
        super().__init__()
        self._user = user

    def compose(self) -> ComposeResult:
        with Vertical(id="modal"):
            yield Label("Edit User")
            yield Input(value=self._user.email, id="email")
            yield Input(value=self._user.username, id="username")
            yield Input(value=self._user.user_id, id="user_id")
            yield Static("", id="error")
            with Horizontal():
                yield Button("Update", id="submit", variant="success")
                yield Button("Cancel", id="cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return

        email = self.query_one("#email", Input).value.strip()
        username = self.query_one("#username", Input).value.strip()
        user_id = self.query_one("#user_id", Input).value.strip()

        if not email or not username or not user_id:
            self.query_one("#error", Static).update(
                "Email, username, and userID are required."
            )
            return

        self.dismiss(EditUserResult(email=email, username=username, user_id=user_id))


class UpdatePasswordScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, user: StaticPasswordUser) -> None:
        super().__init__()
        self._user = user

    def compose(self) -> ComposeResult:
        with Vertical(id="modal"):
            yield Label(f"Set password for {self._user.email}")
            yield Input(placeholder="new password", password=True, id="password")
            yield Input(
                placeholder="confirm password", password=True, id="password_confirm"
            )
            yield Static("", id="error")
            with Horizontal():
                yield Button("Update", id="submit", variant="success")
                yield Button("Cancel", id="cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return

        password = self.query_one("#password", Input).value
        password_confirm = self.query_one("#password_confirm", Input).value

        if not password:
            self.query_one("#error", Static).update("Password is required.")
            return
        if password != password_confirm:
            self.query_one("#error", Static).update("Passwords do not match.")
            return

        self.dismiss(password)


class ConfirmDeleteScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, user: StaticPasswordUser) -> None:
        super().__init__()
        self._user = user

    def compose(self) -> ComposeResult:
        with Vertical(id="modal"):
            yield Label("Delete User")
            yield Static(
                f"Delete {self._user.email} ({self._user.user_id})?", id="confirm_text"
            )
            with Horizontal():
                yield Button("Delete", id="submit", variant="error")
                yield Button("Cancel", id="cancel")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "submit")


class PasswordsManagerApp(App[None]):
    CSS = """
    #main {
        padding: 1;
        height: 100%;
    }
    #toolbar {
        height: auto;
        margin: 1 0;
    }
    #status {
        margin-top: 1;
    }
    #modal {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $panel;
        align: center middle;
    }
    #error {
        color: $error;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("a", "add_user", "Add"),
        Binding("e", "edit_user", "Edit"),
        Binding("p", "set_password", "Password"),
        Binding("d", "delete_user", "Delete"),
        Binding("s", "save", "Save"),
        Binding("r", "reload", "Reload"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, controller: PasswordsController) -> None:
        super().__init__()
        self.controller = controller
        self._visible_users: list[StaticPasswordUser] = []
        self._quit_armed = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main"):
            yield Label(f"Dex Static Passwords: {self.controller.file_path}")
            yield Input(placeholder="Filter by email, username, or userID", id="filter")
            yield DataTable(id="users")
            with Horizontal(id="toolbar"):
                yield Button("Add", id="add", variant="primary")
                yield Button("Edit", id="edit")
                yield Button("Set Password", id="password")
                yield Button("Delete", id="delete", variant="error")
                yield Button("Save", id="save", variant="success")
                yield Button("Reload", id="reload")
            yield Static("Ready", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#users", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("Email", "Username", "userID")
        self._refresh_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self._refresh_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "add": self.action_add_user,
            "edit": self.action_edit_user,
            "password": self.action_set_password,
            "delete": self.action_delete_user,
            "save": self.action_save,
            "reload": self.action_reload,
        }
        action = actions.get(event.button.id)
        if action:
            action()

    def action_add_user(self) -> None:
        self._quit_armed = False

        def _after(result: AddUserResult | None) -> None:
            if result is None:
                return
            try:
                self.controller.create_user(
                    email=result.email,
                    username=result.username,
                    user_id=result.user_id,
                    plain_password=result.password,
                )
            except PasswordsError as exc:
                self._set_status(str(exc), is_error=True)
                return
            self._refresh_table()
            self._set_status(f"Created user {result.email}")

        self.push_screen(AddUserScreen(), _after)

    def action_edit_user(self) -> None:
        self._quit_armed = False
        user = self._selected_user()
        if not user:
            self._set_status("Select a user first.", is_error=True)
            return

        original_user_id = user.user_id

        def _after(result: EditUserResult | None) -> None:
            if result is None:
                return
            try:
                self.controller.update_user(
                    current_user_id=original_user_id,
                    email=result.email,
                    username=result.username,
                    user_id=result.user_id,
                )
            except PasswordsError as exc:
                self._set_status(str(exc), is_error=True)
                return
            self._refresh_table(selected_user_id=result.user_id)
            self._set_status(f"Updated user {result.email}")

        self.push_screen(EditUserScreen(user), _after)

    def action_set_password(self) -> None:
        self._quit_armed = False
        user = self._selected_user()
        if not user:
            self._set_status("Select a user first.", is_error=True)
            return

        user_id = user.user_id

        def _after(password: str | None) -> None:
            if password is None:
                return
            try:
                self.controller.update_password(
                    user_id=user_id, plain_password=password
                )
            except PasswordsError as exc:
                self._set_status(str(exc), is_error=True)
                return
            self._refresh_table(selected_user_id=user_id)
            self._set_status(f"Updated password for {user.email}")

        self.push_screen(UpdatePasswordScreen(user), _after)

    def action_delete_user(self) -> None:
        self._quit_armed = False
        user = self._selected_user()
        if not user:
            self._set_status("Select a user first.", is_error=True)
            return

        user_id = user.user_id

        def _after(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                self.controller.delete_user(user_id=user_id)
            except PasswordsError as exc:
                self._set_status(str(exc), is_error=True)
                return
            self._refresh_table()
            self._set_status(f"Deleted user {user.email}")

        self.push_screen(ConfirmDeleteScreen(user), _after)

    def action_save(self) -> None:
        self._quit_armed = False
        try:
            self.controller.save()
        except PasswordsError as exc:
            self._set_status(str(exc), is_error=True)
            return
        self._set_status("Saved static-passwords file.")

    def action_reload(self) -> None:
        self._quit_armed = False
        try:
            self.controller.reload()
        except PasswordsError as exc:
            self._set_status(str(exc), is_error=True)
            return
        self._refresh_table()
        self._set_status("Reloaded from disk.")

    def action_quit(self) -> None:
        if self.controller.dirty:
            if not self._quit_armed:
                self._quit_armed = True
                self._set_status(
                    "Unsaved changes. Press 's' to save or 'q' again to quit.",
                    is_error=True,
                )
                return
        self.exit()

    def _selected_user(self) -> StaticPasswordUser | None:
        table = self.query_one("#users", DataTable)
        index = table.cursor_row
        if index is None:
            return None
        if index < 0 or index >= len(self._visible_users):
            return None
        return self._visible_users[index]

    def _refresh_table(self, selected_user_id: str | None = None) -> None:
        table = self.query_one("#users", DataTable)
        filter_text = self.query_one("#filter", Input).value.strip().lower()
        users = self.controller.list_users()

        if filter_text:
            users = [
                user
                for user in users
                if filter_text in user.email.lower()
                or filter_text in user.username.lower()
                or filter_text in user.user_id.lower()
            ]

        users = sorted(users, key=lambda u: (u.email.lower(), u.user_id.lower()))
        self._visible_users = users

        table.clear(columns=False)
        selected_index = 0
        for idx, user in enumerate(users):
            table.add_row(user.email, user.username, user.user_id)
            if selected_user_id and user.user_id == selected_user_id:
                selected_index = idx

        if users:
            table.move_cursor(row=selected_index)

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        dirty = "*" if self.controller.dirty else ""
        status = f"{message} {dirty}".strip()
        widget = self.query_one("#status", Static)
        widget.update(status)
        widget.styles.color = "red" if is_error else "green"
