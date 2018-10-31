import hmac
import hashlib
import time
import requests
import logging
import json
import sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO)


class Trading(object):

    ClOrdID = '84262088'

    def __init__(self, key='api key here',
                 secret='api secret here'):
        self.key = key
        self.secret = secret

    def get_signature(self, nonce):
        # gera um hash SHA256 assinado por sua api_secret
        dig = hmac.new(self.secret.encode(), msg=str(nonce).encode(), digestmod=hashlib.sha256)
        return dig.digest().hex()

    def mount_basic_header(self):
        nonce = str(int(time.time()))
        return {
            'APIKey': self.key,
            'Nonce': nonce,
            'Signature': self.get_signature(nonce),
            'Content-Type': 'application/json'
        }

    def __put_order__(self, amount, price, type):
        """
        posiciona uma ordem no livro
        :param amount: volume
        :param price: preço por unidade
        :param type: se eh de compra (buy) ou venda (sell)
        :return:
        """
        resp = {'Status': 401}
        tries = 0
        while resp['Status'] == 401 and tries < 3:
            headers = self.mount_basic_header()
            if type == 'buy':
                t = '1'
            else:
                t = '2'
            message = {
                "MsgType": "D",
                "ClOrdID": self.ClOrdID,
                "Symbol": "BTCBRL",
                "Side": t,
                "OrdType": "2",
                "Price": int(float(price) * 1e8),
                "OrderQty": int(float(amount) * 1e8),
                "BrokerID": 11
            }
            response = requests.post('https://bitcambio_api.blinktrade.com/tapi/v1/message', json=message, headers=headers)
            resp = response.json()
            tries += 1
        return resp

    def cancel_order(self, order_id):
        """
        cancela uma ordem ativa
        :param order_id: OrderID, obtido dos metadados da ordem
        :return: acknowledgment
        """
        message = {
            'MsgType': 'F',
            'OrderID': order_id,
            'ClOrdID': self.ClOrdID,
        }
        headers = self.mount_basic_header()
        response = requests.post('https://bitcambio_api.blinktrade.com/tapi/v1/message', json=message, headers=headers)
        return response.json()

    def sell_limit_order(self, amount, price):
        """
        posiciona uma ordem de venda no livro que nao necessariamente sera executada na hora
        :param amount: volume que quero vender
        :param price: preço por unidade
        :return: metadados da ordem
        """
        return self.__put_order__(amount, price, 'sell')

    def sell_market_order(self, amount):
        """
        posiciona uma ordem de venda no livro que sera executada na hora
        :param amount: volume a ser vendido
        :return: metadados da ordem
        """
        price = self.amount_price(amount, 'sell')  # captura o preço do topo do livro, para posicionar a ordem no topo
        return self.__put_order__(amount, price, 'sell')

    def buy_limit_order(self, amount, price):
        """
        posiciona uma ordem de compra no livro que nao necessariamente sera executada na hora
        :param amount: volume a ser comprado
        :param price: preço por unidade
        :return: metadados da ordem
        """
        return self.__put_order__(amount, price, 'buy')

    def buy_market_order(self, amount):
        """
        posiciona uma ordem de compra no livro que sera executada na hora
        :param amount: volume a ser comprado
        :return: metadados da ordem
        """
        price = self.amount_price(amount, 'buy')  # captura o preço do topo do livro, para posicionar a ordem no topo
        return self.__put_order__(amount, price, 'buy')

    def amount_price(self, amount: float, type: str) -> float:
        """
        :param amount: volume total de criptomoeda que se deseja comprar ou vender
        :param type: tipo de ordem, pode ser compra (buy) ou venda (sell)
        :return: o preço da unidade pago quando compramos o volume desejado considerando o livro de ordens no momento
        """
        type = 'asks' if type == 'buy' else 'bids'  # define lado do livro que sera olhado (lado oposto do tipo de ordem)
        orderbook = self.orders()[type]             # captura as ordens do lado procurado
        total = 0
        count = 0
        num = 0
        den = 0
        assert sum(o[1] for o in orderbook) >= amount, 'Volume insuficiente'  # checa se a exchange tem volume suficiente
        while total < amount:
            # vai incrmeentando a variavel total ate que ela seja igual ao montante desejado
            if total + orderbook[count][1] > amount:
                # se o montante da ordem atual somado ao total ultrapassa o montante desejado,
                # entao comprarei somente a diferença entre o montante desejado e o total ate agora
                bought = amount - total
            else:
                # caso contrario comprarei o montante inteiro da ordem
                bought = orderbook[count][1]
            total = min(amount, total + orderbook[count][1])  # o total e' no maximo igual ao montante deseajdo
            num += orderbook[count][0] * bought  # numerador e' o valor total em fiat gasto para comprar o total ate agora
            den += bought                        # o denominador e' montante total comprado
            count += 1
        return num / den      # retorna o valor total do montante comprado, dividido pelo montante

    def my_orders(self):
        """
        :return: lista das minhas ordens
        """
        message = {
            'MsgType': 'U4',
            'OrdersReqID': 9300199,
            'Page': 0,
            'PageSize': 10,
        }
        headers = self.mount_basic_header()
        response = requests.post('https://bitcambio_api.blinktrade.com/tapi/v1/message', json=message, headers=headers)
        return response.json()

    def is_order_active(self, order_id):
        """
        :param order_id: OrderID, obtido dos metadados da ordem
        :return: True se a ordem estiver tiva, False caso contrario
        """
        my_orders = self.my_orders()  # pega lista das minhas ordens
        if my_orders['Status'] == 401:  # workaround para bug de InvalidApiKey que acontece as vezes na bitcambio
            return True
        orders = my_orders['Responses'][0]['OrdListGrp']  # lista com metadados das minhas ordens
        # se a ordem com OrderID igual ao order_id tiver status '1' ou '0' quer dizer que ela esta ativa, entao retorna True
        return len([o for o in orders if o[3] in ['0', '1'] and o[1] == order_id]) > 0

    def orders(self):
        """
        :return: retorna orderbook da bitcambio
        """
        r = requests.get('https://bitcambio_api.blinktrade.com/api/v1/BRL/orderbook',
                         headers=self.mount_basic_header(), timeout=1)
        return r.json()

    def ticker(self, _type, active_order=False, amount=-1):
        """
        :param _type: buy ou sell
        :param active_order: considerar taxa de ordem ativa ou passiva?
        :param amount: volume que quero comprar, caso nao seja informado, retorna o preço do ticker da exchange
        :return: ticker da exchange considerando a taxa
        """
        fee = 0
        if active_order:
            _type = 'buy'
            fee = 0.002
        if amount == -1:
            r = requests.get('https://bitcambio_api.blinktrade.com/api/v1/BRL/ticker')
            ans = r.json()
            price = ans[_type]
        else:
            price = self.amount_price(amount, _type)
        return (1 - fee) * price

    def quote_amount(self, price):
        """
        dado o preço retorna o volume que eu consigo comprar com preço atual
        :param price: preço
        :return: volume
        """
        t = self.ticker('buy', True)
        return price / t

    def my_user_id(self):
        """
        :return: ID do usuario
        """
        headers = self.mount_basic_header()
        message = {"MsgType": "U2", "BalanceReqID": 1}
        response = requests.post('https://bitcambio_api.blinktrade.com/tapi/v1/message', json=message, headers=headers)
        return response.json()['Responses'][0]['ClientID']

    def get_balance(self):
        """
        :return: retorna saldo do usuario btc e brl
        """
        headers = self.mount_basic_header()
        message = {"MsgType": "U2", "BalanceReqID": 1}
        response = requests.post('https://bitcambio_api.blinktrade.com/tapi/v1/message', json=message, headers=headers)
        balance = dict()
        balance['btc'] = list()
        balance['brl'] = list()
        balance['brl'].append(float(json.loads(response.text)["Responses"][0]['11']['BRL']) / 100000000)
        balance['btc'].append(float(json.loads(response.text)["Responses"][0]['11']['BTC']) / 100000000)
        return json.dumps(balance, ensure_ascii=False)


def always_on_top(brl, order_type='buy'):
    book_side = 'bids' if order_type == 'buy' else 'asks'  # quero monitorar as ordens de compra ou de venda?
    adder = 0.01 if order_type == 'buy' else -0.01  # se quero comprar, minha ordem deve ser a do topo + 1 centavo, se quero vender deve ser a do topo - 1 centavo

    client = Trading(key='api key here',
                     secret='api secret here')

    put_order_fn = client.buy_limit_order if order_type == 'buy' else client.sell_limit_order  # funçao de compra ou venda dependendo do tipo que escolhi

    my_user_id = client.my_user_id()  # guardo meu user id pra saber se eu sou o dono da ordem do livro ou nao
    current_price = client.ticker('buy') + adder  # o preço inicial vai ser o preço da ordem do topo +/- 1 centavo, para que eu va para o topo
    amount = brl / current_price  # a valor que eu quero gastar dividido pelo preço do topo eh igual ao montante que eu vou negociar

    order = put_order_fn(amount, current_price)  # coloca ordem inicial
    print(order['Responses'][0])
    order_id = order['Responses'][0]['OrderID'] # guardo o ID da ordem posta
    logging.info('Meu Id de usuario eh {}'.format(my_user_id))
    logging.info('Ordem posta: {} {} {} {}'.format(order_id, order_type, amount, current_price))

    while client.is_order_active(order_id):  # enquanto a ordem estiver ativa (i.e. nao foi executada nem cancelada)
        orderbook = client.orders()
        top_order = orderbook[book_side][0]  # lista das ordens do livro do lado que eu estipulei
        logging.info('Top order: {} / My User Id: {}'.format(top_order, my_user_id))
        if top_order[-1] != my_user_id:  # se o dono da ordem do topo nao sou eu, eu preciso colocar minha ordem de volta no topo
            current_price = top_order[0] + adder  # +/- 1 centavo na ordem do topo atual
            client.cancel_order(order_id)  # cancelo minha ordem antiga, ja que ela nao esta mais no topo
            order = put_order_fn(amount, current_price)  # crio uma ordem nova, sera a nova do topo
            print('newOrder', order)
            order_id = order['Responses'][0]['OrderID']  # atualizo o orderID
            logging.info('Ordem posta: {} {} {} {}'.format(order_id, order_type, amount, current_price))
        time.sleep(2)


def many_orders_one_spread(first_price, num_orders, spread_between, order_type='buy'):
    """
    :param first_price: preço em fiat da primeira ordem, as demais  terao precos deduzidos a partir deste valor
    :param num_orders: numero de ordens que quero posicionar
    :param spread_between: spread entre as ordens (percentual) entre 0 e 1
    :param order_type: compra ou venda
    :return:
    """
    signal = -1 if order_type == 'buy' else 1
    client = Trading(key='api key here',
                     secret='api secret here')

    put_order_fn = client.buy_limit_order if order_type == 'buy' else client.sell_limit_order  # funçao de compra ou venda dependendo do tipo que escolhi

    current_price = client.ticker(
        'buy') + 0.01*signal  # o preço inicial vai ser o preço da ordem do topo +/- 1 centavo, para que eu va para o topo
    amount = first_price / current_price  # valor que eu quero gastar dividido pelo preço do topo eh igual ao montante que eu vou negociar
    amount /= num_orders          # divido o valor em num_orders partes iguais
    prices = [current_price, ]    # cada parte vai ter um preço com diferença do spread informado, o preço inicial eh o preço do topo
    orders = []
    for i in range(1, num_orders):
        prices.append(prices[i-1] * (1 + spread_between*signal)) # o preço i eh o preço do topo +/- o spread que eu quero entre as ordens
        orders.append(put_order_fn(amount, prices[i-1]))  # posiciono uma ordem
    orders.append(put_order_fn(amount, prices[-1]))  # a ultima ordem
    print(orders)


if __name__ == '__main__':
    b = Trading()
    print(b.sell_market_order(b.quote_amount(25)))

