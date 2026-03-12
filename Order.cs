using System;
using System.Collections.Generic;
using System.Text;
using Dipendenze_Classi;

namespace Dipendenze_Classi
{
    public class Order
    {
        public void PlaceOrder()
        {
            Console.WriteLine("Order placed for: ");
            EmailSender emailSender = new EmailSender();



        }
    }
}
