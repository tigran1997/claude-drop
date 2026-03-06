#!/usr/bin/env python3
"""Claude Drop — A lightweight system tray chat app for Claude."""

import os
import subprocess
import sys
import tempfile
import threading

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')

try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except ValueError:
    print("ERROR: Missing dependency. Install it with:")
    print("  sudo apt install gir1.2-ayatanaappindicator3-0.1")
    print("  gnome-extensions enable ubuntu-appindicators@ubuntu.com")
    sys.exit(1)

from gi.repository import Gtk, Gdk, GLib, Pango


# ── Icon ──────────────────────────────────────────────────────────────────────

ICON_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">
  <polygon points="11,2 20,11 11,20 2,11" fill="#D97706" stroke="#92400E" stroke-width="1"/>
</svg>'''


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = b'''
#claude-drop-panel {
    background-color: #1e1e2e;
    border: 1px solid #45475a;
    border-radius: 12px;
}
#chat-view {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-size: 15px;
}
#chat-view text {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
#input-view {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 8px;
    padding: 8px;
    font-size: 15px;
}
#input-view text {
    background-color: #313244;
    color: #cdd6f4;
}
#progress-bar {
    min-height: 3px;
}
#progress-bar trough {
    min-height: 3px;
    background-color: #1e1e2e;
}
#progress-bar progress {
    min-height: 3px;
    background-color: #D97706;
    border-radius: 2px;
}
#header-bar {
    background-color: #181825;
    border-bottom: 1px solid #45475a;
    padding: 4px 12px;
    border-radius: 12px 12px 0 0;
}
#header-label {
    color: #D97706;
    font-weight: bold;
    font-size: 15px;
}
#auth-label {
    color: #f38ba8;
    font-size: 12px;
}
#tab-bar {
    background-color: #181825;
    border-bottom: 1px solid #45475a;
}
#tab-bar button {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    color: #6c7086;
    padding: 4px 12px;
    font-size: 12px;
    min-height: 0;
    min-width: 0;
}
#tab-bar button:hover {
    color: #cdd6f4;
    background-color: #313244;
}
#tab-bar button.active-tab {
    color: #D97706;
    border-bottom: 2px solid #D97706;
}
#tab-bar .new-tab-btn {
    color: #6c7086;
    padding: 4px 8px;
}
#tab-bar .new-tab-btn:hover {
    color: #D97706;
}
#tab-bar .close-tab-btn {
    color: #6c7086;
    padding: 0 4px;
    min-height: 0;
    min-width: 0;
    font-size: 10px;
}
#tab-bar .close-tab-btn:hover {
    color: #f38ba8;
}
'''


def create_icon_file():
    """Write the SVG icon to a temp file and return the path."""
    path = os.path.join(tempfile.gettempdir(), 'claude-drop-icon.svg')
    with open(path, 'w') as f:
        f.write(ICON_SVG)
    return path


class ChatTab:
    """Holds state for a single conversation tab."""

    _counter = 0

    def __init__(self):
        ChatTab._counter += 1
        self.id = ChatTab._counter
        self.title = f'Chat {self.id}'
        self.history = []  # list of (role, text)
        self.busy = False
        self.pulse_id = None

        # Chat display
        self.chat_buf = Gtk.TextBuffer()
        self._create_tags()
        self.chat_view = Gtk.TextView(buffer=self.chat_buf)
        self.chat_view.set_name('chat-view')
        self.chat_view.set_editable(False)
        self.chat_view.set_cursor_visible(False)
        self.chat_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.chat_view.set_left_margin(12)
        self.chat_view.set_right_margin(12)
        self.chat_view.set_top_margin(8)
        self.chat_view.set_bottom_margin(8)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_vexpand(True)
        self.scroll.add(self.chat_view)

    def _create_tags(self):
        self.chat_buf.create_tag('user-label', foreground='#89b4fa',
                                 weight=Pango.Weight.BOLD, pixels_above_lines=8)
        self.chat_buf.create_tag('user-msg', foreground='#cdd6f4')
        self.chat_buf.create_tag('assistant-label', foreground='#D97706',
                                 weight=Pango.Weight.BOLD, pixels_above_lines=8)
        self.chat_buf.create_tag('assistant-msg', foreground='#cdd6f4')
        self.chat_buf.create_tag('code-block', foreground='#fab387',
                                 family='monospace', background='#11111b',
                                 pixels_above_lines=4, pixels_below_lines=4,
                                 left_margin=20, right_margin=20)
        self.chat_buf.create_tag('system-msg', foreground='#a6adc8',
                                 style=Pango.Style.ITALIC)


class ClaudeDrop:
    PANEL_WIDTH = 400
    PANEL_HEIGHT = 520

    def __init__(self):
        self.tabs = []
        self.active_tab = None
        self._drag_offset = None

        self._setup_css()
        self._build_panel()
        self._add_tab()  # start with one tab
        self._build_indicator()

    # ── CSS ────────────────────────────────────────────────────────────────

    def _setup_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # ── Tray indicator ────────────────────────────────────────────────────

    def _build_indicator(self):
        icon_path = create_icon_file()
        icon_dir = os.path.dirname(icon_path)
        icon_name = os.path.splitext(os.path.basename(icon_path))[0]

        self.indicator = AppIndicator.Indicator.new(
            'claude-drop',
            icon_name,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_icon_theme_path(icon_dir)

        menu = Gtk.Menu()
        toggle_item = Gtk.MenuItem(label='Toggle Claude Drop')
        toggle_item.connect('activate', self._on_toggle)
        menu.append(toggle_item)

        sep = Gtk.SeparatorMenuItem()
        menu.append(sep)

        quit_item = Gtk.MenuItem(label='Quit')
        quit_item.connect('activate', lambda _: Gtk.main_quit())
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)

    # ── Chat panel ────────────────────────────────────────────────────────

    def _build_panel(self):
        self.panel = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.panel.set_name('claude-drop-panel')
        self.panel.set_decorated(False)
        self.panel.set_resizable(False)
        self.panel.set_default_size(self.PANEL_WIDTH, self.PANEL_HEIGHT)
        self.panel.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.panel.set_keep_above(True)
        self.panel.set_skip_taskbar_hint(True)
        self.panel.set_skip_pager_hint(True)

        self._position_panel()

        self.panel.connect('delete-event', lambda w, e: w.hide() or True)
        self.panel.connect('key-press-event', self._on_panel_key)

        # Main layout
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.panel.add(self.vbox)

        # Header (draggable)
        header = Gtk.EventBox()
        header.connect('button-press-event', self._on_header_press)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_box.set_name('header-bar')
        label = Gtk.Label(label='◆ Claude Drop')
        label.set_name('header-label')
        header_box.pack_start(label, False, False, 0)
        header.add(header_box)
        self.vbox.pack_start(header, False, False, 0)

        # Tab bar
        self.tab_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.tab_bar_box.set_name('tab-bar')
        self.tab_buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.tab_bar_box.pack_start(self.tab_buttons_box, True, True, 0)

        new_tab_btn = Gtk.Button(label='+')
        new_tab_btn.get_style_context().add_class('new-tab-btn')
        new_tab_btn.set_relief(Gtk.ReliefStyle.NONE)
        new_tab_btn.connect('clicked', lambda _: self._add_tab())
        self.tab_bar_box.pack_end(new_tab_btn, False, False, 0)
        self.vbox.pack_start(self.tab_bar_box, False, False, 0)

        # Auth error label (hidden by default)
        self.auth_label = Gtk.Label()
        self.auth_label.set_name('auth-label')
        self.auth_label.set_line_wrap(True)
        self.auth_label.set_no_show_all(True)
        self.auth_label.hide()
        self.vbox.pack_start(self.auth_label, False, False, 4)

        # Chat area placeholder — tabs swap their scroll widget in here
        self.chat_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.chat_container.set_vexpand(True)
        self.vbox.pack_start(self.chat_container, True, True, 0)

        # Progress bar
        self.progress = Gtk.ProgressBar()
        self.progress.set_name('progress-bar')
        self.progress.set_no_show_all(True)
        self.progress.hide()
        self.vbox.pack_start(self.progress, False, False, 0)

        # Input area
        input_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        input_frame.set_margin_start(8)
        input_frame.set_margin_end(8)
        input_frame.set_margin_top(4)
        input_frame.set_margin_bottom(8)

        self.input_buf = Gtk.TextBuffer()
        self.input_view = Gtk.TextView(buffer=self.input_buf)
        self.input_view.set_name('input-view')
        self.input_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input_view.set_size_request(-1, 60)
        self.input_view.connect('key-press-event', self._on_input_key)

        input_frame.pack_start(self.input_view, False, False, 0)
        self.vbox.pack_start(input_frame, False, False, 0)

    def _position_panel(self):
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geom = monitor.get_geometry()
        scale = monitor.get_scale_factor()

        x = geom.x + geom.width * scale - self.PANEL_WIDTH - 12
        y = geom.y + geom.height * scale - self.PANEL_HEIGHT - 12
        self.panel.move(int(x), int(y))

    # ── Window dragging ───────────────────────────────────────────────────

    def _on_header_press(self, _widget, event):
        if event.button == 1:
            # Use GTK's native drag which works on both X11 and Wayland
            self.panel.begin_move_drag(
                event.button,
                int(event.x_root),
                int(event.y_root),
                event.time
            )
        return True

    # ── Tabs ──────────────────────────────────────────────────────────────

    def _add_tab(self):
        tab = ChatTab()
        self.tabs.append(tab)
        self._switch_to_tab(tab)
        self._rebuild_tab_bar()

    def _close_tab(self, tab):
        if len(self.tabs) <= 1:
            return  # don't close last tab
        idx = self.tabs.index(tab)
        self.tabs.remove(tab)
        # Clean up pulse timer
        if tab.pulse_id:
            GLib.source_remove(tab.pulse_id)
        # Switch to adjacent tab
        if self.active_tab == tab:
            new_idx = min(idx, len(self.tabs) - 1)
            self._switch_to_tab(self.tabs[new_idx])
        self._rebuild_tab_bar()

    def _switch_to_tab(self, tab):
        # Remove current chat widget from container
        for child in self.chat_container.get_children():
            self.chat_container.remove(child)

        self.active_tab = tab
        self.chat_container.pack_start(tab.scroll, True, True, 0)
        self.chat_container.show_all()

        # Update progress bar visibility
        if tab.busy:
            self.progress.show()
        else:
            self.progress.hide()

        self._rebuild_tab_bar()

    def _rebuild_tab_bar(self):
        for child in self.tab_buttons_box.get_children():
            self.tab_buttons_box.remove(child)

        for idx, tab in enumerate(self.tabs):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)

            btn = Gtk.Button(label=f'{idx + 1}. {tab.title}')
            btn.set_relief(Gtk.ReliefStyle.NONE)
            if tab == self.active_tab:
                btn.get_style_context().add_class('active-tab')
            btn.connect('clicked', lambda _, t=tab: self._switch_to_tab(t))
            box.pack_start(btn, False, False, 0)

            if len(self.tabs) > 1:
                close_btn = Gtk.Button(label='x')
                close_btn.set_relief(Gtk.ReliefStyle.NONE)
                close_btn.get_style_context().add_class('close-tab-btn')
                close_btn.connect('clicked', lambda _, t=tab: self._close_tab(t))
                box.pack_start(close_btn, False, False, 0)

            self.tab_buttons_box.pack_start(box, False, False, 0)

        self.tab_buttons_box.show_all()

    # ── Toggle / keys ─────────────────────────────────────────────────────

    def _on_toggle(self, _widget=None):
        if self.panel.get_visible():
            self.panel.hide()
        else:
            self._position_panel()
            self.panel.show_all()
            self.auth_label.hide()
            if not self.active_tab.busy:
                self.progress.hide()
            self.input_view.grab_focus()

    def _on_panel_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.panel.hide()
            return True
        # Ctrl+K to clear
        if event.keyval == Gdk.KEY_k and event.state & Gdk.ModifierType.CONTROL_MASK:
            self._clear_active_tab()
            return True
        # Ctrl+T for new tab
        if event.keyval == Gdk.KEY_t and event.state & Gdk.ModifierType.CONTROL_MASK:
            self._add_tab()
            return True
        # Ctrl+W to close current tab
        if event.keyval == Gdk.KEY_w and event.state & Gdk.ModifierType.CONTROL_MASK:
            self._close_tab(self.active_tab)
            return True
        # Alt+1..9 to switch tabs
        if event.state & Gdk.ModifierType.MOD1_MASK:
            num = event.keyval - Gdk.KEY_1  # 0-indexed
            if 0 <= num < len(self.tabs):
                self._switch_to_tab(self.tabs[num])
                return True
        return False

    def _on_input_key(self, _widget, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                return False
            self._send_message()
            return True
        return False

    # ── Clear ─────────────────────────────────────────────────────────────

    def _clear_active_tab(self):
        tab = self.active_tab
        tab.history.clear()
        tab.chat_buf.set_text('')
        self.input_buf.set_text('')
        ChatTab._counter -= 0  # keep counter, just reset title
        tab.title = f'Chat {tab.id}'
        self._rebuild_tab_bar()
        self._append_system(tab, 'Conversation cleared.')

    # ── Sending / receiving ───────────────────────────────────────────────

    def _send_message(self):
        tab = self.active_tab
        text = self.input_buf.get_text(
            self.input_buf.get_start_iter(),
            self.input_buf.get_end_iter(), False
        ).strip()
        if not text or tab.busy:
            return

        if text == '/clear':
            self._clear_active_tab()
            return

        self.input_buf.set_text('')

        # Auto-title the tab from first message
        if not tab.history:
            tab.title = text[:16] + ('...' if len(text) > 16 else '')
            self._rebuild_tab_bar()

        self._append_user(tab, text)
        tab.history.append(('user', text))

        tab.busy = True
        self.progress.show()
        tab.pulse_id = GLib.timeout_add(50, self._pulse_progress)

        thread = threading.Thread(target=self._call_claude, args=(tab, text), daemon=True)
        thread.start()

    def _pulse_progress(self):
        if self.active_tab.busy:
            self.progress.pulse()
            return True
        return False

    def _call_claude(self, tab, user_text):
        """Run claude -p in a subprocess (background thread)."""
        prompt_parts = []
        for role, msg in tab.history[:-1]:
            prefix = 'User' if role == 'user' else 'Assistant'
            prompt_parts.append(f'{prefix}: {msg}')
        prompt_parts.append(f'User: {user_text}')
        full_prompt = '\n\n'.join(prompt_parts)

        env = os.environ.copy()
        env.pop('CLAUDECODE', None)

        try:
            result = subprocess.run(
                ['claude', '-p', full_prompt],
                capture_output=True, text=True, timeout=120, env=env
            )

            if result.returncode != 0:
                stderr = result.stderr.strip()
                if 'auth' in stderr.lower() or 'login' in stderr.lower() or 'credential' in stderr.lower():
                    GLib.idle_add(self._show_auth_error, stderr)
                else:
                    GLib.idle_add(self._append_error, tab, stderr or f'claude exited with code {result.returncode}')
                GLib.idle_add(self._finish_loading, tab)
                return

            response = result.stdout.strip()
            if not response:
                response = '(empty response)'

            tab.history.append(('assistant', response))
            GLib.idle_add(self._append_assistant, tab, response)

        except subprocess.TimeoutExpired:
            GLib.idle_add(self._append_error, tab, 'Request timed out (120s)')
        except FileNotFoundError:
            GLib.idle_add(self._append_error, tab,
                          'claude CLI not found. Install: npm install -g @anthropic-ai/claude-code')
        except Exception as e:
            GLib.idle_add(self._append_error, tab, str(e))
        finally:
            GLib.idle_add(self._finish_loading, tab)

    def _finish_loading(self, tab):
        tab.busy = False
        if tab.pulse_id:
            GLib.source_remove(tab.pulse_id)
            tab.pulse_id = None
        if tab == self.active_tab:
            self.progress.hide()

    # ── Message rendering ─────────────────────────────────────────────────

    def _append_user(self, tab, text):
        buf = tab.chat_buf
        end = buf.get_end_iter()
        if buf.get_char_count() > 0:
            buf.insert(end, '\n')
            end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, 'You\n', 'user-label')
        end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, text + '\n', 'user-msg')
        self._scroll_to_bottom(tab)

    def _append_assistant(self, tab, text):
        buf = tab.chat_buf
        end = buf.get_end_iter()
        if buf.get_char_count() > 0:
            buf.insert(end, '\n')
            end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, 'Claude\n', 'assistant-label')
        self._render_with_code_fences(tab, text, 'assistant-msg')
        self._scroll_to_bottom(tab)

    def _render_with_code_fences(self, tab, text, default_tag):
        buf = tab.chat_buf
        parts = text.split('```')
        for i, part in enumerate(parts):
            if not part:
                continue
            end = buf.get_end_iter()
            if i % 2 == 0:
                buf.insert_with_tags_by_name(end, part, default_tag)
            else:
                lines = part.split('\n', 1)
                code = lines[1] if len(lines) > 1 else lines[0]
                buf.insert_with_tags_by_name(end, '\n' + code.strip() + '\n', 'code-block')
        end = buf.get_end_iter()
        buf.insert(end, '\n')

    def _append_system(self, tab, text):
        buf = tab.chat_buf
        end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, text + '\n', 'system-msg')
        self._scroll_to_bottom(tab)

    def _append_error(self, tab, text):
        self._append_system(tab, f'Error: {text}')

    def _show_auth_error(self, details):
        self.auth_label.set_text(
            'Authentication error. Run `claude` in a terminal to log in.'
        )
        self.auth_label.show()
        self._append_error(self.active_tab, details)

    def _scroll_to_bottom(self, tab):
        if tab == self.active_tab:
            GLib.idle_add(self._do_scroll, tab)

    def _do_scroll(self, tab):
        end = tab.chat_buf.get_end_iter()
        tab.chat_view.scroll_to_iter(end, 0.0, False, 0, 0)
        return False

    # ── Run ───────────────────────────────────────────────────────────────

    def run(self):
        Gtk.main()


def main():
    app = ClaudeDrop()
    app.run()


if __name__ == '__main__':
    main()
