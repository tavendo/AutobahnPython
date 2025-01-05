###############################################################################
#
# The MIT License (MIT)
#
# Copyright (c) typedef int GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
###############################################################################

import os
import argparse
import uuid
import binascii
import random
from pprint import pprint
from time import time_ns

import sys
if sys.version_info < (3, 10):
    import importlib_resources as resources
else:
    from importlib import resources

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from gi.repository.Gdk import Color

from twisted.internet import gtk3reactor
gtk3reactor.install()

import txaio
txaio.use_twisted()

from twisted.internet.task import react
from twisted.internet.defer import inlineCallbacks
from twisted.internet import reactor

import web3

import numpy as np

import click
from humanize import naturaldelta, naturaltime

from autobahn.util import parse_activation_code, hltype, hlid, hlval
from autobahn.wamp.serializer import CBORSerializer
from autobahn.twisted.util import sleep
from autobahn.twisted.wamp import ApplicationRunner
from autobahn.xbr import unpack_uint256
from autobahn.xbr import account_from_seedphrase, generate_seedphrase, account_from_ethkey
from autobahn.xbr._cli import Client
from autobahn.xbr._config import UserConfig, Profile

LOGO_RESOURCE = str(resources.files('autobahn.asset') / 'xbr_gray.svg')
print(LOGO_RESOURCE, os.path.isfile(LOGO_RESOURCE))


class ApplicationWindow(Gtk.Assistant):
    """
    Main application window which provides UI for the following functions:

    * N) New account
    * R) Recover account:
       - R1) Backup cloud device in account enabled => download encrypted account data
           from cloud backup device, requires email (and 2FA) verification and password
       - R2) At least one device left in account and at hand => synchronize with existing device,
           direct device-to-device encrypted account data transfer
       - R3) Only cold storage recovery seed phrase left => account from seed-phrase full
           recovery, including new email and 2FA verification.

    See also:
    * https://python-gtk-3-tutorial.readthedocs.io/en/latest/
    * https://twistedmatrix.com/documents/current/core/howto/choosing-reactor.html
    """
    log = txaio.make_logger()

    SELECTED_NONE = 0
    SELECTED_NEW = 1
    SELECTED_SYNCRONIZE = 2
    SELECTED_RECOVER = 3

    def __init__(self, reactor, session, config, config_path, profile, profile_name):
        Gtk.Assistant.__init__(self)

        self.reactor = reactor
        self.session = session
        self.config = config
        self.config_path = config_path
        self.profile = profile
        self.profile_name = profile_name

        self.input_seedphrase = None
        self.input_email = None
        self.input_password = None

        self.output_account = None
        self.output_ethadr = None
        self.output_ethadr_raw = None
        self.output_member_data = None
        self.output_member_data_oid = uuid.UUID(bytes=b'\x00' * 16)

        # configure assistant window/widget
        self.set_title("XBR Network")
        self.set_default_size(600, 600)
        self.set_border_width(50)
        self.set_resizable(False)

        # setup assistant pages
        self._setup_page1()
        self._setup_page2()
        self._setup_page3()
        self._setup_page4()
        self._setup_page5()

    @inlineCallbacks
    def start(self):
        # start page depends on available user profile
        if self.profile:
            self.output_account = account_from_ethkey(self.profile.ethkey)
            self.output_ethadr = web3.Web3.toChecksumAddress(self.output_account.address)
            self.output_ethadr_raw = binascii.a2b_hex(self.output_ethadr[2:])
            info = yield self.session.get_status()
            if info:
                now = str(np.datetime64(np.datetime64(info['status']['now'], 'ns'), 's'))
                self._label5_now.set_label(now)
                self._label5_chain.set_label(str(info['status']['chain']))
                self._label5_status.set_label(str(info['status']['status']))
                self._label5_xbrnetwork.set_label(str(info['config']['contracts']['xbrnetwork']))
                self._label5_xbrtoken.set_label(str(info['config']['contracts']['xbrtoken']))
                self._label5_blockhash.set_label('0x' + binascii.b2a_hex(info['status']['block']['hash']).decode())
                self._label5_blocknumber.set_label(str(info['status']['block']['number']))

            pprint(info)
            member_data = yield self.session.get_member(self.output_ethadr_raw)
            if not member_data:
                self.log.info('ethadr {output_ethadr} is NOT yet a member',
                              output_ethadr=self.output_ethadr)
                if self.profile.vaction_oid:
                    # switch to page "_setup_page4"
                    self.set_current_page(3)
                else:
                    if self.profile.ethkey:
                        # switch to page "_setup_page3"
                        self.set_current_page(2)
                    else:
                        # switch to page "_setup_page2"
                        self.set_current_page(1)
            else:
                self.log.info('ok, ethadr {output_ethadr} already is a member: {member_data}',
                              output_ethadr=self.output_ethadr, member_data=member_data)
                self.output_member_data = member_data
                created_ago = naturaldelta((np.datetime64(time_ns(), 'ns') - self.output_member_data['created']) / 1000000000.)
                created = naturaltime(np.datetime64(self.output_member_data['created'], 's'))
                self._label2.set_label(str(self.output_member_data['oid']))
                self._label4.set_label(str(self.output_member_data['address']))
                self._label6.set_label('{} ({} ago)'.format(created, created_ago))
                self._label8.set_label(str(self.output_member_data['level']))
                self._label10.set_label(str(self.output_member_data['balance']['eth']))
                self._label12.set_label(str(self.output_member_data['balance']['xbr']))

                # switch to page "_setup_page5"
                self.set_current_page(4)
        else:
            profile = Profile()
            profile.path = self.config_path
            profile.ethkey = None
            profile.cskey = None
            profile.username = None
            profile.email = None
            profile.network_url = 'ws://localhost:8090/ws'
            profile.network_realm = 'xbrnetwork'
            profile.member_oid = None
            profile.vaction_oid = None
            profile.vaction_requested = None
            profile.vaction_verified = None
            profile.data_url = None
            profile.data_realm = None
            profile.infura_url = None
            profile.infura_network = None
            profile.infura_key = None
            profile.infura_secret = None
            self.profile = profile

            # switch to page "_setup_page1"
            self.set_current_page(0)

    def on_complete_toggled(self, checkbutton):
        self.set_page_complete(self.complete, checkbutton.get_active())

    # no config: select new/recovery
    def _setup_page1(self):
        """
        Setup page shown when no config/profile could be found. Allows to select from:

        * new account
        * synchronize device
        * recover account
        """
        grid1 = Gtk.Grid()
        grid1.set_row_spacing(20)
        grid1.set_column_spacing(20)
        grid1.set_margin_top(20)
        grid1.set_margin_bottom(20)
        grid1.set_margin_start(20)
        grid1.set_margin_end(20)

        image1 = Gtk.Image()

        image1.set_from_file(LOGO_RESOURCE)
        grid1.attach(image1, 0, 0, 2, 1)

        label0 = Gtk.Label(label='\n\nI am new and do not have an account yet:\n')
        label0.set_alignment(0, 0.5)
        grid1.attach(label0, 0, 1, 2, 1)

        label1 = Gtk.Label(label='Create a new account or start from fresh. You only need an email address. [N]')
        label1.set_alignment(0, 0.5)
        label1.set_justify(Gtk.Justification.LEFT)
        grid1.attach(label1, 1, 2, 1, 1)

        button1 = Gtk.Button.new_with_label('New account')

        def on_button1(res):
            self.log.info('SELECTED_NEW: {res}', res=res)
            self.set_current_page(1)

        button1.connect('clicked', on_button1)
        grid1.attach(button1, 0, 2, 1, 1)

        label12 = Gtk.Label(label='\n\nI already have an existing account and want to use that:\n')
        label12.set_alignment(0, 0.5)
        grid1.attach(label12, 0, 3, 2, 1)

        label22 = Gtk.Label(label='Restore account from cloud backup to this device. You will need access to\n'
                                  'your account password and access to your account email address. [R1]')
        label22.set_alignment(0, 0.5)
        label22.set_justify(Gtk.Justification.LEFT)
        label22.set_line_wrap(True)
        label22.set_width_chars(12)
        grid1.attach(label22, 1, 4, 1, 1)

        button22 = Gtk.Button.new_with_label('Restore account')

        def on_button22(res):
            self.log.info('SELECTED_RESTORE: {res}', res=res)
            self.set_current_page(2)

        button22.connect('clicked', on_button22)
        grid1.attach(button22, 0, 4, 1, 1)

        label2 = Gtk.Label(label='Synchronize device with other device in account. You will need access to\n'
                                 'another device currently connected to your account. [R2]')
        label2.set_alignment(0, 0.5)
        label2.set_justify(Gtk.Justification.LEFT)
        label2.set_line_wrap(True)
        label2.set_width_chars(12)
        grid1.attach(label2, 1, 5, 1, 1)

        button2 = Gtk.Button.new_with_label('Synchronize account')

        def on_button2(res):
            self.log.info('SELECTED_SYNCRONIZE: {res}', res=res)
            self.set_current_page(2)

        button2.connect('clicked', on_button2)
        grid1.attach(button2, 0, 5, 1, 1)

        label3 = Gtk.Label(label='Recover account from account seed phrase. You only need access to\n'
                                 'your 12-24 word account recovery seed phrase. [R3]')
        label3.set_alignment(0, 0.5)
        label3.set_justify(Gtk.Justification.LEFT)
        label3.set_line_wrap(True)
        label3.set_width_chars(12)
        grid1.attach(label3, 1, 6, 1, 1)

        button3 = Gtk.Button.new_with_label('Recover account')

        def on_button3(res):
            self.log.info('SELECTED_RECOVER: {res}', res=res)
            self.set_current_page(3)

        button3.connect('clicked', on_button3)
        grid1.attach(button3, 0, 6, 1, 1)

        self.append_page(grid1)

    # generate seed phrase
    def _setup_page2(self):
        """
        Setup page shown to generate a new seed phrase.
        """
        box2_1 = Gtk.VBox()

        box2_2 = Gtk.HBox()
        image2_1 = Gtk.Image()
        image2_1.set_from_file(LOGO_RESOURCE)
        box2_2.add(image2_1)
        box2_1.add(box2_2)

        button2_1 = Gtk.Button.new_with_label('Generate seedphrase')

        def on_button2_1(_):
            self.input_seedphrase = generate_seedphrase(strength=256, language='english')
            textbuffer2_1.set_text(self.input_seedphrase)
            checkbutton2_1.set_sensitive(True)

        button2_1.connect('clicked', on_button2_1)
        box2_1.add(button2_1)

        label2_1 = Gtk.Label(label='Backup your new seed phrase in a secure offline location (e.g. on printed paper):')
        label2_1.set_alignment(0, 0.5)
        label2_1.set_justify(Gtk.Justification.LEFT)
        box2_1.add(label2_1)

        textview2_1 = Gtk.TextView()
        textbuffer2_1 = textview2_1.get_buffer()
        textbuffer2_1.set_text('\n' * 5)
        textview2_1.set_editable(False)
        textview2_1.set_justification(Gtk.Justification.CENTER)
        textview2_1.set_monospace(True)
        textview2_1.set_wrap_mode(Gtk.WrapMode.WORD)
        box2_1.add(textview2_1)

        box2_3 = Gtk.HBox()

        checkbutton2_1 = Gtk.CheckButton(label="I have backed up my seed phrase")
        checkbutton2_1.set_active(False)
        checkbutton2_1.set_sensitive(False)

        def on_checkbutton2_1(_):
            button2_2.set_sensitive(True)

        checkbutton2_1.connect("toggled", on_checkbutton2_1)
        box2_3.add(checkbutton2_1)

        button2_2 = Gtk.Button.new_with_label('Continue')
        button2_2.set_sensitive(False)

        @inlineCallbacks
        def on_button2_2(_):
            self.output_account = account_from_seedphrase(self.input_seedphrase, index=0)
            self.output_ethadr = web3.Web3.toChecksumAddress(self.output_account.address)
            self.output_ethadr_raw = binascii.a2b_hex(self.output_ethadr[2:])

            # https://eth-account.readthedocs.io/en/latest/eth_account.signers.html#eth_account.signers.local.LocalAccount.key
            self.profile.ethkey = bytes(self.output_account.key)
            self.profile.cskey = bytes(self.session._cskey_raw)

            # set user eth key on client session
            self.session.set_ethkey_from_profile(self.profile)

            # save user config
            self.config.profiles[self.profile_name] = self.profile
            self.config.save(self.input_password)

            self.log.info('XBR ETH key at address {ethadr} set from seed phrase (BIP39 account 0): "{seedphrase}"',
                          ethadr=self.output_ethadr,
                          seedphrase=self.input_seedphrase)

            member_data = yield self.session.get_member(self.output_ethadr_raw)
            pprint(member_data)
            if not member_data:
                self.log.info('ethadr {output_ethadr} is NOT yet a member',
                              output_ethadr=self.output_ethadr)
                self.set_current_page(2)
            else:
                self.log.info('ok, ethadr {output_ethadr} already is a member: {member_data}',
                              output_ethadr=self.output_ethadr, member_data=member_data)

                self.profile.member_oid = uuid.UUID(bytes=member_data['member_oid'])
                self.profile.member_adr = self.output_ethadr
                self.profile.email = member_data['email']
                self.profile.username = member_data['username']

                # save user config
                self.config.profiles[self.profile_name] = self.profile
                self.config.save(self.input_password)

                self.output_member_data = member_data
                self._label2.set_label(str(self._member_data['oid']))
                self.set_current_page(4)

        def run_on_button2_2(widget):
            self.log.info('{func}({widget})', func=hltype(run_on_button2_2), widget=widget)
            reactor.callLater(0, on_button2_2, widget)

        button2_2.connect('clicked', run_on_button2_2)
        box2_3.add(button2_2)

        box2_1.add(box2_3)

        self.append_page(box2_1)

    # submit onboard request
    def _setup_page3(self):
        """

        :return:
        """
        box1 = Gtk.VBox()

        box2 = Gtk.HBox()
        image1 = Gtk.Image()
        image1.set_from_file(LOGO_RESOURCE)
        box2.add(image1)
        box1.add(box2)

        grid1 = Gtk.Grid()
        grid1.set_row_spacing(20)
        grid1.set_column_spacing(20)
        grid1.set_margin_top(20)
        grid1.set_margin_bottom(20)
        grid1.set_margin_start(20)
        grid1.set_margin_end(20)

        label1 = Gtk.Label(label='Your email address:')
        grid1.attach(label1, 0, 0, 1, 1)

        entry1 = Gtk.Entry()
        entry1.set_text('')
        entry1.set_max_length(255)
        entry1.set_max_width_chars(40)
        grid1.attach(entry1, 1, 0, 1, 1)

        checks = {
            'email': None,
            'password': None,
            'eula': None,
        }

        def check_all():
            print('check_all')
            for c in checks:
                if checks[c] is None:
                    print('check failed', c)
                    button3.set_sensitive(False)
                    return
            button3.set_sensitive(True)

        def check_email(email):
            if '@' in email:
                return email
            else:
                return None

        def check_password(password):
            return True

        def on_entry1(entry):
            # joe.doe@example.com
            checks['email'] = check_email(entry.get_text())
            if checks['email']:
                entry1.modify_fg(Gtk.StateFlags.NORMAL, None)
            else:
                entry1.modify_fg(Gtk.StateFlags.NORMAL, Color(50000, 0, 0))
            check_all()

        entry1.connect('changed', on_entry1)

        label2 = Gtk.Label(label='New password:')
        grid1.attach(label2, 0, 1, 1, 1)

        entry2 = Gtk.Entry()
        entry2.set_text('')
        entry2.set_max_length(20)
        entry2.set_max_width_chars(20)
        entry2.set_visibility(False)
        grid1.attach(entry2, 1, 1, 1, 1)

        label2 = Gtk.Label(label='Repeat new password:')
        grid1.attach(label2, 0, 2, 1, 1)

        entry3 = Gtk.Entry()
        entry3.set_text('')
        entry3.set_max_length(20)
        entry3.set_max_width_chars(20)
        entry3.set_visibility(False)
        grid1.attach(entry3, 1, 2, 1, 1)

        def on_entry23(_):
            pw1_ok = False
            if check_password(entry2.get_text()):
                pw1_ok = True
                entry2.modify_fg(Gtk.StateFlags.NORMAL, None)
            else:
                entry2.modify_fg(Gtk.StateFlags.NORMAL, Color(50000, 0, 0))

            pw2_ok = False
            if check_password(entry3.get_text()):
                pw2_ok = True
                entry3.modify_fg(Gtk.StateFlags.NORMAL, None)
            else:
                entry3.modify_fg(Gtk.StateFlags.NORMAL, Color(50000, 0, 0))

            if pw1_ok and pw2_ok and entry2.get_text() == entry3.get_text() and check_password(entry2.get_text()):
                checks['password'] = entry2.get_text()
            else:
                checks['password'] = None

            check_all()

        entry2.connect('changed', on_entry23)
        entry3.connect('changed', on_entry23)

        label3 = Gtk.Label(label='EULA:')
        grid1.attach(label3, 0, 3, 1, 1)

        button1 = Gtk.CheckButton(label='I accept the EULA and terms of use')
        button1.set_active(False)
        button1.set_sensitive(True)

        def on_button1(button):
            if button.get_active():
                checks['eula'] = True
            else:
                checks['eula'] = False
            check_all()

        button1.connect('toggled', on_button1)
        grid1.attach(button1, 1, 3, 1, 1)

        label3 = Gtk.Label(label='Cloud backup:')
        grid1.attach(label3, 0, 4, 1, 1)

        button2 = Gtk.CheckButton(label='Yes, enable encrypted cloud backup of my private keys')
        button2.set_active(False)
        button2.set_sensitive(True)

        def on_button2(button):
            check_all()

        button2.connect('toggled', on_button2)
        grid1.attach(button2, 1, 4, 1, 1)

        button3 = Gtk.Button.new_with_label('Register account')
        button3.set_sensitive(False)

        @inlineCallbacks
        def on_button3(_):
            self.input_email = checks['email']
            self.input_password = checks['password']
            self.input_backup_enabled = button2.get_active()
            self.input_username = 'anonymous'
            self.input_username = '{}{}'.format(self.input_username, random.randint(0, 10000))

            self.session.set_ethkey_from_profile(self.profile)

            self.log.info('input_email: {input_email}', input_email=self.input_email)
            self.log.info('input_username: {input_username}', input_username=self.input_username)
            self.log.info('input_password: {input_password}', input_password=self.input_password)
            result = yield self.session._do_onboard_member(self.input_username, self.input_email)
            pprint(result)

            self.profile.email = self.input_email
            self.profile.username = self.input_username
            self.profile.vaction_oid = str(uuid.UUID(bytes=result['vaction_oid']))
            self.profile.vaction_requested = str(np.datetime64(result['timestamp'], 'ns'))

            self.config.profiles[self.profile_name] = self.profile
            self.config.save(self.input_password)

            self.set_current_page(3)

        def run_on_button3(widget):
            self.log.info('{func}({widget})', func=hltype(run_on_button3), widget=widget)
            reactor.callLater(0, on_button3, widget)

        button3.connect('clicked', run_on_button3)
        grid1.attach(button3, 2, 4, 1, 1)

        box1.add(grid1)

        self.append_page(box1)

    # submit verification code
    def _setup_page4(self):
        """
        Page shown when member registration request was submitted, a verification email
        sent, and the verification request ID returned.
        The user now should check the email inbox for the received verification code,
        and continue verifying the code.

        :return:
        """
        box1 = Gtk.VBox()

        box2 = Gtk.HBox()
        image1 = Gtk.Image()
        image1.set_from_file(LOGO_RESOURCE)
        box2.add(image1)
        box1.add(box2)

        box3 = Gtk.HBox()
        label1 = Gtk.Label(label='Member registration submitted, verification request:')
        label2 = Gtk.Label(label='8d5d7ffd-23d9-45a0-a686-00a49f29d3cd')
        box3.add(label1)
        box3.add(label2)
        box1.add(box3)

        label3 = Gtk.Label(label='Please check your email inbox, and enter the verification code received here:')
        box1.add(label3)

        entry1 = Gtk.Entry()
        entry1.set_text('')
        entry1.set_max_length(255)
        entry1.set_max_width_chars(40)
        box1.add(entry1)

        def on_entry1(entry):
            # "RWCN-94NV-CEHR" -> ("RWCN", "94NV", "CEHR") | None
            vaction_code = parse_activation_code(entry.get_text())
            if vaction_code:
                entry1.modify_fg(Gtk.StateFlags.NORMAL, None)
                button1.set_sensitive(True)
            else:
                entry1.modify_fg(Gtk.StateFlags.NORMAL, Color(50000, 0, 0))
                button1.set_sensitive(False)

        entry1.connect('changed', on_entry1)

        button1 = Gtk.Button.new_with_label('Verify')
        button1.set_sensitive(False)

        @inlineCallbacks
        def on_button1(_):
            vaction_code = parse_activation_code(entry1.get_text())
            if vaction_code:
                vaction_code = '-'.join(vaction_code.groups())
            if type(self.profile.vaction_oid) == str:
                vaction_oid = uuid.UUID(self.profile.vaction_oid)
            else:
                vaction_oid = self.profile.vaction_oid
            result = yield self.session._do_onboard_member_verify(vaction_oid, vaction_code)
            pprint(result)

            self.profile.vaction_verified = str(np.datetime64(result['created'], 'ns'))
            self.profile.vaction_transaction = '0x' + str(binascii.b2a_hex(result['transaction']).decode())
            self.profile.member_oid = str(uuid.UUID(bytes=result['member_oid']))
            self.config.profiles[self.profile_name] = self.profile
            self.config.save(self.input_password)

        def run_on_button1(widget):
            self.log.info('{func}({widget})', func=hltype(run_on_button1), widget=widget)
            reactor.callLater(0, on_button1, widget)

        button1.connect('clicked', run_on_button1)
        box1.add(button1)

        self.append_page(box1)

    # show member data
    def _setup_page5(self):
        """
        Page shown for a user (private eth key) that already is member.

        :return:
        """
        box1 = Gtk.VBox()

        box2 = Gtk.HBox()
        image1 = Gtk.Image()
        image1.set_from_file(LOGO_RESOURCE)
        box2.add(image1)
        box1.add(box2)

        grid2 = Gtk.Grid()
        grid2.set_row_spacing(20)
        grid2.set_column_spacing(20)
        grid2.set_margin_top(20)
        grid2.set_margin_bottom(20)
        grid2.set_margin_start(20)
        grid2.set_margin_end(20)

        grid2_y = 0

        # Current server time
        #
        label5_now_title = Gtk.Label(label='Current server time:')
        label5_now_title.set_alignment(1, 0.5)
        grid2.attach(label5_now_title, 0, grid2_y, 1, 1)
        self._label5_now = Gtk.Label()
        self._label5_now.set_alignment(0, 0.5)
        self._label5_now.set_selectable(False)
        grid2.attach(self._label5_now, 1, grid2_y, 1, 1)
        grid2_y += 1

        # Blockchain ID (e.g. 1, 3 or 5777)
        #
        label5_chain_title = Gtk.Label(label='Blockchain ID:')
        label5_chain_title.set_alignment(1, 0.5)
        grid2.attach(label5_chain_title, 0, grid2_y, 1, 1)
        self._label5_chain = Gtk.Label()
        self._label5_chain.set_alignment(0, 0.5)
        self._label5_chain.set_selectable(True)
        grid2.attach(self._label5_chain, 1, grid2_y, 1, 1)
        grid2_y += 1

        # Current server time
        #
        label5_status_title = Gtk.Label(label='Service status:')
        label5_status_title.set_alignment(1, 0.5)
        grid2.attach(label5_status_title, 0, grid2_y, 1, 1)
        self._label5_status = Gtk.Label()
        self._label5_status.set_alignment(0, 0.5)
        self._label5_status.set_selectable(False)
        grid2.attach(self._label5_status, 1, grid2_y, 1, 1)
        grid2_y += 1

        # xbrnetwork address
        #
        label5_xbrnetwork_title = Gtk.Label(label='XBRNetwork contract:')
        label5_xbrnetwork_title.set_alignment(1, 0.5)
        grid2.attach(label5_xbrnetwork_title, 0, grid2_y, 1, 1)
        self._label5_xbrnetwork = Gtk.Label()
        self._label5_xbrnetwork.set_alignment(0, 0.5)
        self._label5_xbrnetwork.set_selectable(True)
        grid2.attach(self._label5_xbrnetwork, 1, grid2_y, 1, 1)
        grid2_y += 1

        # xbrtoken address
        #
        label5_xbrtoken_title = Gtk.Label(label='XBRToken contract:')
        label5_xbrtoken_title.set_alignment(1, 0.5)
        grid2.attach(label5_xbrtoken_title, 0, grid2_y, 1, 1)
        self._label5_xbrtoken = Gtk.Label()
        self._label5_xbrtoken.set_alignment(0, 0.5)
        self._label5_xbrtoken.set_selectable(True)
        grid2.attach(self._label5_xbrtoken, 1, grid2_y, 1, 1)
        grid2_y += 1

        # Current block hash
        #
        label5_blockhash_title = Gtk.Label(label='Current block hash:')
        label5_blockhash_title.set_alignment(1, 0.5)
        grid2.attach(label5_blockhash_title, 0, grid2_y, 1, 1)
        self._label5_blockhash = Gtk.Label()
        self._label5_blockhash.set_alignment(0, 0.5)
        self._label5_blockhash.set_selectable(True)
        grid2.attach(self._label5_blockhash, 1, grid2_y, 1, 1)
        grid2_y += 1

        # Current block number
        #
        label5_blocknumber_title = Gtk.Label(label='Current block number:')
        label5_blocknumber_title.set_alignment(1, 0.5)
        grid2.attach(label5_blocknumber_title, 0, grid2_y, 1, 1)
        self._label5_blocknumber = Gtk.Label()
        self._label5_blocknumber.set_alignment(0, 0.5)
        self._label5_blocknumber.set_selectable(True)
        grid2.attach(self._label5_blocknumber, 1, grid2_y, 1, 1)
        grid2_y += 1

        box1.add(grid2)

        grid1 = Gtk.Grid()
        grid1.set_row_spacing(20)
        grid1.set_column_spacing(20)
        grid1.set_margin_top(20)
        grid1.set_margin_bottom(20)
        grid1.set_margin_start(20)
        grid1.set_margin_end(20)

        label1 = Gtk.Label(label='User ID:')
        label1.set_alignment(1, 0.5)
        grid1.attach(label1, 0, 0, 1, 1)

        self._label2 = Gtk.Label()
        self._label2.set_alignment(0, 0.5)
        self._label2.set_selectable(True)
        grid1.attach(self._label2, 1, 0, 1, 1)

        label3 = Gtk.Label(label='Eth Address:')
        label3.set_alignment(1, 0.5)
        grid1.attach(label3, 0, 1, 1, 1)

        self._label4 = Gtk.Label()
        self._label4.set_alignment(0, 0.5)
        self._label4.set_selectable(True)
        grid1.attach(self._label4, 1, 1, 1, 1)

        label5 = Gtk.Label(label='Account Created:')
        label5.set_alignment(1, 0.5)
        grid1.attach(label5, 0, 2, 1, 1)

        self._label6 = Gtk.Label()
        self._label6.set_alignment(0, 0.5)
        grid1.attach(self._label6, 1, 2, 1, 1)

        label7 = Gtk.Label(label='Membership:')
        label7.set_alignment(1, 0.5)
        grid1.attach(label7, 0, 3, 1, 1)

        self._label8 = Gtk.Label()
        self._label8.set_alignment(0, 0.5)
        grid1.attach(self._label8, 1, 3, 1, 1)

        label9 = Gtk.Label(label='ETH Balance:')
        label9.set_alignment(1, 0.5)
        grid1.attach(label9, 0, 4, 1, 1)

        self._label10 = Gtk.Label()
        self._label10.set_alignment(0, 0.5)
        grid1.attach(self._label10, 1, 4, 1, 1)

        label11 = Gtk.Label(label='XBR Balance:')
        label11.set_alignment(1, 0.5)
        grid1.attach(label11, 0, 5, 1, 1)

        self._label12 = Gtk.Label()
        self._label12.set_alignment(0, 0.5)
        grid1.attach(self._label12, 1, 5, 1, 1)

        box1.add(grid1)

        self.append_page(box1)


class ApplicationClient(Client):
    async def onJoin(self, details):
        self.log.info('Ok, client joined on realm "{realm}" [session={session}, authid="{authid}", authrole="{authrole}"]',
                      realm=hlid(details.realm),
                      session=hlid(details.session),
                      authid=hlid(details.authid),
                      authrole=hlid(details.authrole),
                      details=details)
        if 'ready' in self.config.extra:
            txaio.resolve(self.config.extra['ready'], (self, details))

    @inlineCallbacks
    def get_status(self):
        if self.is_attached():
            config = yield self.call('xbr.network.get_config')
            status = yield self.call('xbr.network.get_status')
            return {'config': config, 'status': status}
        else:
            self.log.warn('not connected: could not retrieve status')

    @inlineCallbacks
    def get_member(self, ethadr_raw):
        if self.is_attached():
            is_member = yield self.call('xbr.network.is_member', ethadr_raw)
            if is_member:
                member_data = yield self.call('xbr.network.get_member_by_wallet', ethadr_raw)

                member_data['address'] = web3.Web3.toChecksumAddress(member_data['address'])
                member_data['oid'] = uuid.UUID(bytes=member_data['oid'])
                member_data['balance']['eth'] = web3.Web3.fromWei(unpack_uint256(member_data['balance']['eth']),
                                                                  'ether')
                member_data['balance']['xbr'] = web3.Web3.fromWei(unpack_uint256(member_data['balance']['xbr']),
                                                                  'ether')
                member_data['created'] = np.datetime64(member_data['created'], 'ns')

                member_level = member_data['level']
                member_data['level'] = {
                    # Member is active.
                    1: 'ACTIVE',
                    # Member is active and verified.
                    2: 'VERIFIED',
                    # Member is retired.
                    3: 'RETIRED',
                    # Member is subject to a temporary penalty.
                    4: 'PENALTY',
                    # Member is currently blocked and cannot current actively participate in the market.
                    5: 'BLOCKED',
                }.get(member_level, None)

                self.log.info(
                    'Member {member_oid} found for address 0x{member_adr} - current member level {member_level}',
                    member_level=hlval(member_data['level']),
                    member_oid=hlid(member_data['oid']),
                    member_adr=hlval(member_data['address']))

                return member_data
            else:
                self.log.warn('Address {output_ethadr} is not a member in the XBR network',
                              output_ethadr=ethadr_raw)
        else:
            self.log.warn('not connected: could not retrieve member data for address {output_ethadr}',
                          output_ethadr=ethadr_raw)


class Application(object):
    """
    Main XBR member application.
    """
    log = txaio.make_logger()

    DOTDIR = os.path.abspath(os.path.expanduser('~/.xbrnetwork'))
    DOTFILE = 'config.ini'

    async def start(self, reactor, url=None, realm=None, profile=None):
        """
        Start main application. This will read the user configuration, potentially asking
        for a user password.

        :param reactor: Twisted reactor to use.
        :param url: Optionally override network URL as defined in profile.
        :param realm: Optionally override network URL as defined in profile.
        :param profile: User profile name to load.
        :return:
        """
        txaio.start_logging(level='info')

        self.log.info('ok, application starting for user profile "{profile}"', profile=profile)

        if not os.path.isdir(self.DOTDIR):
            os.mkdir(self.DOTDIR)
            self.log.info('dotdir created: "{dotdir}"', dotdir=self.DOTDIR)

        self._config_path = config_path = os.path.join(self.DOTDIR, self.DOTFILE)
        self._profile_name = profile or 'default'
        if not os.path.isfile(self._config_path):
            self.log.info('no config exist under "{config_path}"', config_path=self._config_path)
            self._config = UserConfig(self._config_path)
            self._profile = None
        else:
            self._config = UserConfig(self._config_path)
            # FIXME: start modal dialog to get password from user

            def getpw():
                return '123secret'

            self._config.load(cb_get_password=getpw)
            if self._profile_name not in self._config.profiles:
                raise click.ClickException('no such profile "{}" in config "{}" with {} profiles'.format(self._profile_name, config_path, len(self._config.profiles)))
            else:
                self._profile = self._config.profiles[self._profile_name]
                self.log.info('user profile "{profile_name}" loaded from "{config_path}":\n\n',
                              config_path=self._config_path, profile_name=self._profile_name)
                pprint(self._profile.marshal())
                print('\n\n')

        extra = {
            'ready': txaio.create_future(),
            'done': txaio.create_future(),
            'running': True,
            'config': self._config,
            'config_path': self._config_path,
            'profile': self._profile,
            'profile_name': self._profile_name,
        }
        # XBR network node used as a directory server and gateway to XBR smart contracts
        network_url = url or (self._profile.network_url if self._profile and self._profile.network_url else 'ws://localhost:8090/ws')

        # WAMP realm on network node, usually "xbrnetwork"
        network_realm = realm or (self._profile.network_realm if self._profile and self._profile.network_realm else 'xbrnetwork')

        runner = ApplicationRunner(url=network_url,
                                   realm=network_realm,
                                   extra=extra,
                                   serializers=[CBORSerializer()])

        self.log.info('ok, now connecting to "{network_url}", joining realm "{network_realm}" ..',
                      network_url=network_url,
                      network_realm=network_realm)
        await runner.run(ApplicationClient,
                         reactor=reactor,
                         auto_reconnect=True,
                         start_reactor=False)
        self.log.info('ok, application client connected!')

        session, details = await extra['ready']
        self.log.info('ok, application session joined: {details}', details=details)

        def on_exit(_):
            self.log.info('exiting application ..')
            extra['running'] = False
            txaio.resolve(extra['done'], None)

        win = ApplicationWindow(reactor, session, self._config, self._config_path, self._profile, self._profile_name)
        win.connect("cancel", on_exit)
        win.connect("destroy", on_exit)
        win.show_all()

        await win.start()

        ticks = 0
        while extra['running']:
            ticks += 1
            self.log.info('ok, application main task still running at tick {ticks}', ticks=ticks)
            await sleep(5)

        self.log.info('ok, application main task ended!')


async def main(reactor, url, realm, profile):
    """
    Load the named user profile (or create a new one), overriding URL/realm,
    connect to a network node, and start the network member on-boarding.

    If the user credentials are already for a member, fetch member information
    and display member page.

    :param reactor: Twisted reactor to use.
    :param url: Override network URL from user profile with this value.
    :param realm: Override network realm from user profile with this value.
    :param profile: Name of user profile within user
        configuration to load (eg from ``$HOME/.xbrnetwork/config.ini``)
    """
    app = Application()
    await app.start(reactor, url=url, realm=realm, profile=profile)


def _main():
    """
    GUI entry point, parsing command line arguments and then starting the
    actual main GUI program with parsed parameters.

    To use, run:

    .. code:: console

        xbrnetwork-ui --profile default --url ws://localhost:8090/ws --realm xbrnetwork

    This will load the user profile ``"default"`` from the user configuration, but
    overriding any network URL and realm found therin.
    """
    parser = argparse.ArgumentParser()

    parser.add_argument('--url',
                        dest='url',
                        type=str,
                        default=None,
                        help='The router URL to connect to, e.g. "ws://localhost:8090/ws"')

    parser.add_argument('--realm',
                        dest='realm',
                        type=str,
                        default=None,
                        help='The realm to join, e.g. "xbrnetwork"')

    parser.add_argument('--profile',
                        dest='profile',
                        type=str,
                        default='default',
                        help='The user profile to use, e.g. "default"')

    args = parser.parse_args()

    react(main, (args.url, args.realm, args.profile,))


if __name__ == '__main__':
    _main()
