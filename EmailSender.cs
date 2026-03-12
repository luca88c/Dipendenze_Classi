using System;
using System.Collections.Generic;
using System.Text;

namespace Dipendenze_Classi
{
    public class EmailSender : Notifiche
    {
        public void SendNotifica(string message)
        {
            Console.WriteLine("Email sent: " + message);
           
        }
    }
}
